import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import tutorialJson from './generated/basics-tutorial.json';
import type { Tutorial } from './generated/lessons';
import { LessonPlayer, intentMatches } from './lesson-player.svelte';
import { loadProgress } from './progress';
import { legalClaimOptions } from '$lib/table/legal-actions';
import { viewFromClientState } from '$lib/table/live-view';

const tutorial = tutorialJson as unknown as Tutorial;
const at = (text: string) =>
	tutorial.steps.findIndex((step) => step.kind !== 'auto' && step.text === text);

let players: LessonPlayer[] = [];
function play(options: ConstructorParameters<typeof LessonPlayer>[1] = {}): LessonPlayer {
	const player = new LessonPlayer(tutorial, options);
	players.push(player);
	return player;
}

beforeEach(() => localStorage.clear());
afterEach(() => {
	for (const player of players) player.destroy();
	players = [];
	vi.useRealTimers();
});

// the hand's tiles by type: the script names one copy, the player may click another.
const PUNG_TILES = [108, 109];
const CHOW_TILES = [8, 16];

describe('LessonPlayer', () => {
	it('starts on the first tip, from the tutorial start position with seats named', () => {
		const player = play();
		expect(player.index).toBe(0);
		expect(player.step).toMatchObject({ kind: 'narrate', text: 'welcome' });
		expect(player.state.ownHand).toHaveLength(13);
		expect(player.state.names[0]).toBe('You');
		expect(player.state.names[1]).toBe('South');
	});

	it('moves past a narrate step on next, and back again', () => {
		const player = play();
		player.next();
		expect(player.step).toMatchObject({ kind: 'narrate', text: 'yourHand' });
		player.back();
		expect(player.index).toBe(0);
	});

	it('plays an auto step at once with no delay, then waits on the next tip', () => {
		const player = play();
		player.next();
		player.next();
		expect(player.index).toBe(at('draw'));
		// north's discard, then your draw
		expect(player.state.discardPools[3]).toEqual([112]);
		expect(player.state.ownHand).toHaveLength(14);
		expect(player.state.drawnTileId).toBe(124);
	});

	it('paces an auto step by the delay', () => {
		vi.useFakeTimers();
		const player = play({ autoDelayMs: 500 });
		player.next();
		player.next();
		expect(player.busy).toBe(true);
		expect(player.state.discardPools[3]).toEqual([]);
		vi.advanceTimersByTime(500);
		expect(player.busy).toBe(false);
		expect(player.step).toMatchObject({ text: 'draw' });
	});

	it('drops every deadline, so no timer shows as expired', () => {
		const player = play();
		player.goTo(at('claimPung'));
		expect(player.state.deadlineTs).toBeNull();
		expect(player.state.claimOffer?.deadlineTs).toBeNull();
		const view = viewFromClientState(player.state)!.view;
		expect(view.turnDurationMs).toBeNull();
		expect(view.handEndHoldMs).toBeNull();
	});

	it('holds on a wrong move at an expect step, and counts it for the hint', () => {
		const player = play();
		player.goTo(at('discardFirst'));
		const before = player.state;
		expect(player.act({ kind: 'discard', tileId: 8 })).toBe(false);
		expect(player.wrongMoves).toBe(1);
		expect(player.index).toBe(at('discardFirst'));
		expect(player.state).toBe(before);
	});

	it('advances on the scripted move, playing its frames and the autos after it', () => {
		const player = play();
		player.goTo(at('discardFirst'));
		expect(player.act({ kind: 'discard', tileId: 128 })).toBe(true);
		expect(player.state.discardPools[0]).toEqual([128]);
		expect(player.step).toMatchObject({ kind: 'narrate', text: 'pungOffer' });
		expect(player.wrongMoves).toBe(0);
	});

	it('matches a discard by tile type, not by id', () => {
		const action = { kind: 'discard', tile_id: 128 };
		expect(intentMatches(action, { kind: 'discard', tileId: 129 })).toBe(true);
		expect(intentMatches(action, { kind: 'discard', tileId: 124 })).toBe(false);
	});

	it('opens the claim window from the snapshot, and only the scripted claim advances', () => {
		const player = play();
		player.goTo(at('claimPung'));
		const view = viewFromClientState(player.state)!.view;
		expect(legalClaimOptions(view.claimWindow)?.map((o) => o.kind)).toEqual(['pung', 'pass']);
		expect(player.act({ kind: 'claim', choice: 'pass' })).toBe(false);
		expect(player.act({ kind: 'claim', choice: 'pung', tiles: PUNG_TILES })).toBe(true);
		expect(player.state.melds[0]).toHaveLength(1);
		// a claim leaves no drawn tile to hold apart, though the snapshot's last tile is one
		player.goTo(at('discardAfterPung'));
		expect(player.state.drawnTileId).toBeNull();
	});

	it('takes the chow, and refuses a pung where a kong is scripted', () => {
		const player = play();
		player.goTo(at('claimChow'));
		expect(player.act({ kind: 'claim', choice: 'chow', tiles: CHOW_TILES })).toBe(true);
		player.goTo(at('claimKong'));
		expect(player.act({ kind: 'claim', choice: 'pung', tiles: [68, 69] })).toBe(false);
		expect(player.act({ kind: 'claim', choice: 'kong', tiles: [68, 69, 70] })).toBe(true);
	});

	it('declares the self-drawn win, ends the hand and records completion', () => {
		const onComplete = vi.fn();
		const player = play({ persist: true, onComplete });
		player.goTo(at('declareWin'));
		expect(player.act({ kind: 'discard', tileId: 40 })).toBe(false);
		expect(player.act({ kind: 'declare_win' })).toBe(true);
		expect(player.isLast).toBe(true);
		expect(player.state.lastHandEnd).toMatchObject({ outcome: 'win', winType: 'self_draw' });
		expect(player.state.handEndDeadlineTs).toBeNull();
		expect(onComplete).toHaveBeenCalledOnce();
		expect(loadProgress()[tutorial.id]).toMatchObject({ solved: true });
		expect(loadProgress()[tutorial.id].step).toBeUndefined();
	});

	it('saves the step it waits on, and resumes there with the same position', () => {
		const first = play({ persist: true });
		first.goTo(at('discardFirst'));
		first.act({ kind: 'discard', tileId: 128 });
		expect(loadProgress()[tutorial.id].step).toBe(at('pungOffer'));
		const resumed = play({ persist: true });
		// opening the page keeps the saved step until the player picks
		expect(loadProgress()[tutorial.id].step).toBe(at('pungOffer'));
		resumed.goTo(loadProgress()[tutorial.id].step!);
		expect(JSON.stringify(resumed.state)).toEqual(JSON.stringify(first.state));
		resumed.restart();
		expect(loadProgress()[tutorial.id].step).toBeUndefined();
	});

	it('counts only the steps that wait on the player', () => {
		const player = play();
		expect(player.waitingCount).toBe(tutorial.steps.filter((s) => s.kind !== 'auto').length);
		player.goTo(at('draw'));
		expect(player.waitingNumber).toBe(3);
	});
});
