import type { ClaimKind } from '$lib/game/types';
import { initialClientGameState, type ClientGameState } from '$lib/game/state';
import type { ServerEvent, StateSync } from '$lib/net/protocol';
import { reduce } from '$lib/net/reducer';
import { tileIdToCode } from '$lib/table/tile-code';
import type { Tutorial, TutorialStep } from './generated/lessons';
import { withSeatNames } from './puzzle-state';
import { saveTutorialDone, saveTutorialStep } from './progress';
import { saveOnboarding } from '$lib/ui/settings-storage';

/** What the player did at an `expect` step, in the table's own intent vocabulary. */
export type TutorialIntent =
	| { kind: 'discard'; tileId: number }
	| { kind: 'claim'; choice: ClaimKind; tiles?: readonly number[] }
	| { kind: 'declare_win' }
	| { kind: 'declare_concealed_kong' | 'declare_added_kong'; tiles: readonly number[] };

export interface LessonPlayerOptions {
	/** pause before each `auto` step; 0 applies it at once. */
	autoDelayMs?: number;
	/** keep `mahjong:learnProgress:v1` current (the resume step, then completion), and finish the
	 * practice coach marks at the end. */
	persist?: boolean;
	/** runs once, when the last step is reached. */
	onComplete?: () => void;
}

type Action = Record<string, unknown>;

function codes(ids: readonly unknown[] | undefined): string[] {
	return (ids ?? []).map((id) => tileIdToCode(id as number)).sort();
}

// a multiset check: every tile type the player named is one the scripted meld uses.
function typesWithin(picked: readonly number[], meld: readonly unknown[] | undefined): boolean {
	const pool = codes(meld);
	for (const code of codes(picked)) {
		const i = pool.indexOf(code);
		if (i === -1) return false;
		pool.splice(i, 1);
	}
	return true;
}

/** Whether `intent` is the scripted `action`. Tiles compare by type, never by id: the script
 * names one physical copy, and the hand may hold another. */
export function intentMatches(action: Action, intent: TutorialIntent): boolean {
	const meld = (action.meld as { tiles?: number[] } | undefined)?.tiles;
	switch (intent.kind) {
		case 'discard':
			return (
				action.kind === 'discard' &&
				tileIdToCode(action.tile_id as number) === tileIdToCode(intent.tileId)
			);
		case 'claim':
			if (intent.choice === 'pass') return action.kind === 'pass';
			return action.kind === `claim_${intent.choice}` && typesWithin(intent.tiles ?? [], meld);
		case 'declare_win':
			return action.kind === 'declare_win';
		case 'declare_concealed_kong':
		case 'declare_added_kong':
			return action.kind === intent.kind && typesWithin(intent.tiles, meld);
	}
}

// tutorial frames carry deadline 0 (no clock, protocol.md §6): left in, every ring reads as
// expired and the claim dialog's timer would pass at once.
function withoutDeadlines(state: ClientGameState): ClientGameState {
	return {
		...state,
		deadlineTs: null,
		handEndDeadlineTs: null,
		claimOffer: state.claimOffer ? { ...state.claimOffer, deadlineTs: null } : null
	};
}

function applySnapshot(prev: ClientGameState, snapshot: StateSync): ClientGameState {
	return withSeatNames(reduce(prev, snapshot));
}

function applyFrames(state: ClientGameState, frames: readonly ServerEvent[]): ClientGameState {
	return frames.reduce(reduce, state);
}

/** True for the steps that wait on the player: a tip to read, or a move to make. */
export function isWaitingStep(step: TutorialStep): boolean {
	return step.kind !== 'auto';
}

/** Plays a generated tutorial through the client reducer, with no socket: `narrate` waits for
 * `next()`, `auto` applies its frames after a pause, `expect` waits for the scripted `act()`. */
export class LessonPlayer {
	readonly tutorial: Tutorial;
	state = $state<ClientGameState>(initialClientGameState());
	/** the step being shown, or run when it is an `auto` one. */
	index = $state(0);
	/** wrong moves at the current `expect` step; the hint shows once this is nonzero. */
	wrongMoves = $state(0);

	readonly #autoDelayMs: number;
	readonly #persist: boolean;
	readonly #onComplete: (() => void) | undefined;
	#timer: ReturnType<typeof setTimeout> | null = null;
	#completed = false;

	constructor(tutorial: Tutorial, options: LessonPlayerOptions = {}) {
		this.tutorial = tutorial;
		this.#autoDelayMs = options.autoDelayMs ?? 0;
		this.#persist = options.persist ?? false;
		this.#onComplete = options.onComplete;
		this.goTo(0);
	}

	get step(): TutorialStep | null {
		return this.tutorial.steps[this.index] ?? null;
	}

	/** an `auto` step is still playing: the table is not the player's to act on. */
	get busy(): boolean {
		return this.step?.kind === 'auto';
	}

	get isLast(): boolean {
		return this.index >= this.tutorial.steps.length - 1;
	}

	/** waiting steps, numbered from 1, for the "step n of total" counter. */
	get waitingCount(): number {
		return this.tutorial.steps.filter(isWaitingStep).length;
	}

	get waitingNumber(): number {
		return this.tutorial.steps.slice(0, this.index + 1).filter(isWaitingStep).length;
	}

	get previousWaiting(): number | null {
		for (let i = this.index - 1; i >= 0; i--) {
			if (isWaitingStep(this.tutorial.steps[i])) return i;
		}
		return null;
	}

	/** Past a `narrate` tip. */
	next(): void {
		if (this.step?.kind !== 'narrate' || this.isLast) return;
		this.#enter(this.index + 1);
	}

	back(): void {
		const target = this.previousWaiting;
		if (target !== null) this.goTo(target);
	}

	restart(): void {
		if (this.#persist) saveTutorialStep(this.tutorial.id, null);
		this.goTo(0);
	}

	/** The player's move at an `expect` step: the scripted one plays its frames and moves on;
	 * anything else counts as a wrong move and changes nothing. */
	act(intent: TutorialIntent): boolean {
		const step = this.step;
		if (step?.kind !== 'expect') return false;
		if (!intentMatches(step.action, intent)) {
			this.wrongMoves += 1;
			return false;
		}
		this.state = withoutDeadlines(applyFrames(this.state, step.frames));
		this.#enter(this.index + 1);
		return true;
	}

	/** Jump to step `target`: replays every step before it at once, from the start position. */
	goTo(target: number): void {
		this.#cancel();
		let state = withSeatNames(reduce(initialClientGameState(), this.tutorial.start));
		const end = Math.min(Math.max(target, 0), this.tutorial.steps.length - 1);
		for (const step of this.tutorial.steps.slice(0, end)) {
			if (step.kind === 'expect') state = applySnapshot(state, step.snapshot);
			if (step.kind !== 'narrate') state = applyFrames(state, step.frames);
		}
		this.state = withoutDeadlines(state);
		this.#enter(end);
	}

	destroy(): void {
		this.#cancel();
	}

	#cancel(): void {
		if (this.#timer !== null) clearTimeout(this.#timer);
		this.#timer = null;
	}

	#enter(index: number): void {
		this.index = index;
		this.wrongMoves = 0;
		const step = this.step;
		if (step === null) return;
		if (step.kind === 'auto') {
			const play = () => {
				this.#timer = null;
				this.state = withoutDeadlines(applyFrames(this.state, step.frames));
				this.#enter(index + 1);
			};
			if (this.#autoDelayMs > 0) this.#timer = setTimeout(play, this.#autoDelayMs);
			else play();
			return;
		}
		if (step.kind === 'expect') {
			this.state = withoutDeadlines(applySnapshot(this.state, step.snapshot));
		}
		if (this.isLast) this.#complete();
		// step 0 saves nothing, so opening the page keeps the resume point it offers.
		else if (this.#persist && index > 0) saveTutorialStep(this.tutorial.id, index);
	}

	#complete(): void {
		if (this.#persist) {
			saveTutorialDone(this.tutorial.id);
			// the first practice hand's coach marks would only repeat what this taught.
			saveOnboarding({ coachMarksDone: true });
		}
		if (this.#completed) return;
		this.#completed = true;
		this.#onComplete?.();
	}
}
