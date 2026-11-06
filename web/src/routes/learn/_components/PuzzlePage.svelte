<script lang="ts">
	import { tick, type Snippet } from 'svelte';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import AnswerPanel from '$lib/learn/AnswerPanel.svelte';
	import { grade } from '$lib/learn/grade';
	import {
		BAND_LABEL,
		TRACK_LABEL,
		indexHref,
		lessonEntry,
		nextLesson,
		previousLesson,
		trackPosition
	} from '$lib/learn/lessons';
	import {
		LESSON_TEXT,
		lessonSubtitle,
		lessonTextParams,
		lessonTitle
	} from '$lib/learn/lesson-text';
	import { loadProgress, nextUnsolved, saveAttempt } from '$lib/learn/progress';
	import { learnSync } from '$lib/learn/learn-sync.svelte';
	import { isMotionReduced } from '$lib/ui/motion';
	import { puzzleState } from '$lib/learn/puzzle-state';
	import type { Answer, GradeResult } from '$lib/learn/types';
	import { m } from '$lib/paraglide/messages.js';
	import CenterHub from '$lib/table/CenterHub.svelte';
	import type { Lesson } from '$lib/learn/generated/lessons';
	import { legalDiscardIds } from '$lib/table/legal-actions';
	import { ownHandTiles as handTiles, viewFromClientState } from '$lib/table/live-view';
	import TableScene from '$lib/table/TableScene.svelte';
	import { tileIdToCode } from '$lib/table/tile-code';
	import type { HandTileMark } from '$lib/table/view-types';
	import BackButton from '$lib/ui/BackButton.svelte';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';

	let {
		lesson,
		backHref,
		navExtra,
		afterCorrect,
		onGraded,
		onReveal
	}: {
		lesson: Lesson;
		/** the "All puzzles" link; the lesson's own track tab by default. */
		backHref?: string;
		navExtra?: Snippet;
		/** replaces the Next link once solved or revealed. */
		afterCorrect?: Snippet;
		/** replaces saving to learn progress. */
		onGraded?: (result: GradeResult) => void;
		/** the player asked for the answer after a miss. */
		onReveal?: () => void;
	} = $props();

	let gameState = $derived(puzzleState(lesson));
	// the snapshot always seats you at 0, so the projection is never null.
	let live = $derived(viewFromClientState(gameState)!);
	let view = $derived(live.view);
	let text = $derived(LESSON_TEXT[lesson.text]);
	let params = $derived(lessonTextParams(lesson));
	let title = $derived(lessonTitle(lesson));
	// endless puzzles aren't in the index, so they get no number
	let subtitle = $derived.by(() => {
		const entry = lessonEntry(lesson.id);
		return entry ? lessonSubtitle(entry) : null;
	});
	let previous = $derived(previousLesson(lesson.id));
	let next = $derived(nextLesson(lesson.id));
	// endless isn't a walk through the index, even when a pool id matches one
	let position = $derived(onGraded ? null : trackPosition(lesson.id));
	// other lessons' progress changes only when a signed-in account's arrives; this one is skipped
	let nextOpen = $derived(
		onGraded ? null : (void learnSync.version, nextUnsolved(loadProgress(), lesson.id))
	);
	let nextHref = $derived(nextOpen ? `/learn/${nextOpen.id}` : '/learn');

	let result = $state<GradeResult | null>(null);
	let lastAnswer = $state<Answer | null>(null);
	let attempts = $state(0);
	let solvedBefore = $state(false);
	let guideFocus = $state<string | null>(null);
	let revealed = $state(false);
	// the hand's lifted tile (picked, not yet graded) and the tile of the last graded pick
	let selectedTileId = $state<number | null>(null);
	let pickedTileId = $state<number | null>(null);
	$effect.pre(() => {
		const id = lesson.id;
		result = null;
		lastAnswer = null;
		attempts = 0;
		guideFocus = null;
		revealed = false;
		selectedTileId = null;
		pickedTileId = null;
		solvedBefore = onGraded ? false : (loadProgress()[id]?.solved ?? false);
	});

	// a discard win: the claimed tile is the snapshot's last discard
	let claimedTile = $derived(
		lesson.kind === 'count_faan' && lesson.key.win_type === 'discard' && gameState.lastDiscard
			? tileIdToCode(gameState.lastDiscard.tileId)
			: null
	);

	let ownHandTiles = $derived(handTiles(live.ownHand));

	let answersByDiscard = $derived(lesson.kind === 'best_discard' || lesson.kind === 'safe_discard');
	let discardableTileIds = $derived(
		answersByDiscard ? legalDiscardIds(gameState.legalActions) : new Set<number>()
	);

	function answer(given: Answer): void {
		result = grade(lesson, given).result;
		lastAnswer = given;
		attempts += 1;
		selectedTileId = null;
		if (onGraded) onGraded(result);
		else saveAttempt(lesson.id, result === 'correct');
	}

	// a second tap on the lifted tile, or Check on it
	function discard(tileId: number): void {
		if (lesson.kind !== 'best_discard' && lesson.kind !== 'safe_discard') return;
		pickedTileId = tileId;
		answer({ kind: lesson.kind, tile: tileIdToCode(tileId) });
	}

	function checkSelected(): void {
		if (selectedTileId !== null) discard(selectedTileId);
	}

	// reveals without solving: a later right answer still grades and saves as usual
	function reveal(): void {
		revealed = true;
		onReveal?.();
	}

	let selectedTile = $derived(selectedTileId === null ? null : tileIdToCode(selectedTileId));
	let answerShown = $derived(result === 'correct' || (result !== null && revealed));

	// the graded pick in brass; the answer tiles in green once shown
	let tileMarks = $derived.by(() => {
		const marks = new Map<number, HandTileMark>();
		if (lesson.kind !== 'best_discard' && lesson.kind !== 'safe_discard') return marks;
		if (pickedTileId !== null) marks.set(pickedTileId, 'pick');
		if (!answerShown) return marks;
		const correct: readonly string[] = lesson.key.correct;
		for (const tile of ownHandTiles) {
			if (tile.tileId !== null && correct.includes(tile.code)) marks.set(tile.tileId, 'answer');
		}
		return marks;
	});

	let solved = $derived(solvedBefore || result === 'correct');

	// waits and best discard read visible tiles (dead waits, unseen counts), so only safe_discard's
	// opponents stay whole and only count_faan loses their discards too
	let dimOpponents = $derived<'hands' | 'all' | null>(
		lesson.kind === 'count_faan' ? 'all' : lesson.kind === 'safe_discard' ? null : 'hands'
	);

	let pageEl: HTMLDivElement | null = $state(null);
	let nextActionsEl: HTMLDivElement | null = $state(null);

	// below desktop-up the answer card sits under the table, so a result can land off-screen
	$effect(() => {
		if (result === null) return;
		void attempts;
		void revealed;
		void tick().then(() => {
			const status = pageEl?.querySelector<HTMLElement>('[data-testid="answer-feedback"]');
			if (!status) return;
			const box = status.getBoundingClientRect();
			if (box.top >= 0 && box.bottom <= window.innerHeight) return;
			status.scrollIntoView({ block: 'nearest', behavior: isMotionReduced() ? 'auto' : 'smooth' });
		});
	});

	function ignoredKey(event: KeyboardEvent): boolean {
		if (event.defaultPrevented || event.repeat) return true;
		if (event.ctrlKey || event.metaKey || event.altKey || event.shiftKey) return true;
		const target = event.target instanceof Element ? event.target : null;
		if (target?.closest('input, textarea, select, [contenteditable], dialog')) return true;
		return document.querySelector('dialog[open]') !== null;
	}

	function onKeydown(event: KeyboardEvent): void {
		if (ignoredKey(event)) return;
		const target = event.target instanceof Element ? event.target : null;
		if (event.key === 'Enter') {
			// a focused control's own Enter already does its thing; a solved answer isn't re-sent
			if (result === 'correct' || target?.closest('button, a, summary, [role="button"]')) return;
			const check = pageEl?.querySelector<HTMLButtonElement>('[data-testid="answer-check"]');
			if (!check || check.disabled) return;
			event.preventDefault();
			check.click();
		} else if (event.key === 'n' || event.key === 'N') {
			const action = nextActionsEl?.querySelector<HTMLElement>('a, button:not(:disabled)');
			if (!action) return;
			event.preventDefault();
			action.click();
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<svelte:head>
	<title>{m.learn_lessonPageTitle({ title })}</title>
</svelte:head>

{#snippet hub()}
	<CenterHub
		prevailing={view.prevailing}
		handNo={view.handNo}
		dealer={view.dealer}
		turn={view.turn}
		you={view.you}
		wallCount={view.wallCount}
		minFaan={gameState.ruleset?.min_faan ?? null}
		turnDurationMs={null}
	/>
{/snippet}

{#key lesson.id}
	<div
		class="puzzle-page"
		bind:this={pageEl}
		data-testid="puzzle-page"
		data-kind={lesson.kind}
		data-lesson={lesson.id}
	>
		<nav class="puzzle-nav">
			<BackButton label={m.learn_indexLabel()} href={backHref ?? indexHref(lesson.track)} />
			<span class="step-links">
				{#if previous}
					<a
						class="step-link"
						href="/learn/{previous.id}"
						data-sfx="on"
						data-testid="lesson-previous"
					>
						<ChevronLeft size={18} aria-hidden="true" />
						<span>{m.learn_previousLabel()}</span>
					</a>
				{/if}
				{#if next}
					<a class="step-link" href="/learn/{next.id}" data-sfx="on" data-testid="lesson-next">
						<span>{m.learn_nextLabel()}</span>
						<ChevronRight size={18} aria-hidden="true" />
					</a>
				{/if}
				{@render navExtra?.()}
			</span>
		</nav>

		<section class="prompt-card" aria-labelledby="puzzle-title">
			<p class="meta">
				{#if position}
					<span class="position" data-testid="puzzle-position"
						>{m.learn_trackPosition({
							track: TRACK_LABEL[position.track](),
							n: position.n,
							total: position.total
						})}</span
					>
				{/if}
				<span class="band">{BAND_LABEL[lesson.band]()}</span>
				{#if subtitle}
					<span data-testid="puzzle-sub">{subtitle}</span>
				{/if}
				{#if solved}
					<span class="solved" data-testid="puzzle-solved">
						<CircleCheck size={16} aria-hidden="true" />
						{m.learn_solvedMark()}
					</span>
				{/if}
			</p>
			<h1 id="puzzle-title">{title}</h1>
			<p class="prompt" data-testid="puzzle-prompt">{text.prompt(params)}</p>
		</section>

		<div class="puzzle-table">
			{#key attempts}
				<TableScene
					{view}
					spectating={false}
					isMock={false}
					turn={view.turn}
					{hub}
					{ownHandTiles}
					{discardableTileIds}
					declareOptions={[]}
					discardMode="two-step"
					onDiscard={discard}
					holdLastDiscard={claimedTile !== null}
					bind:liftedTileId={selectedTileId}
					{tileMarks}
					{dimOpponents}
				/>
			{/key}
		</div>

		<section class="answer-card">
			<AnswerPanel
				{lesson}
				answer={lastAnswer}
				{result}
				{attempts}
				explanation={text.explain(params)}
				seatNames={gameState.names}
				{claimedTile}
				{selectedTile}
				{revealed}
				onAnswer={answer}
				onCheckSelected={checkSelected}
				onReveal={reveal}
				onPatternSelect={(pattern) => (guideFocus = pattern)}
			/>
			{#if answerShown}
				<div class="next-actions" bind:this={nextActionsEl}>
					{#if afterCorrect}
						{@render afterCorrect()}
					{:else}
						<a
							class="next-button"
							href={nextHref}
							data-sfx="on"
							data-testid="answer-next"
							aria-keyshortcuts="N">{nextOpen ? m.learn_nextLabel() : m.learn_nextDoneLabel()}</a
						>
					{/if}
					<span class="key-hint" data-testid="next-key-hint" aria-hidden="true"
						>{m.learn_nextKeyHint()}</span
					>
				</div>
			{/if}
		</section>
	</div>

	{#if guideFocus !== null}
		<GuideDialog
			onClose={() => (guideFocus = null)}
			tableRules={gameState.ruleset}
			tablePreset={gameState.rulesetPreset}
			focusPattern={guideFocus}
		/>
	{/if}
{/key}

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.puzzle-page {
		display: grid;
		grid-template-areas: 'nav' 'prompt' 'table' 'answer';
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-3);
		padding: var(--space-4);

		@include layout.desktop-up {
			grid-template-areas: 'nav nav' 'table prompt' 'table answer';
			grid-template-columns: minmax(0, 1fr) 24rem;
			grid-template-rows: auto auto minmax(0, 1fr);
			height: 100dvh;
			padding: var(--space-4) var(--space-5);
		}
	}

	.puzzle-nav {
		grid-area: nav;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}

	.step-links {
		display: flex;
		gap: var(--space-2);
	}

	.step-link {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-ghost;
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		text-decoration: none;
	}

	.prompt-card,
	.answer-card {
		@include buttons.panel-elevated;
		padding: var(--space-4);
		background: var(--color-surface);
	}

	.prompt-card {
		grid-area: prompt;

		h1 {
			margin: var(--space-1) 0 var(--space-2);
			font-size: var(--font-size-xl);
		}
	}

	.meta {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.solved {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		color: var(--color-positive);
	}

	.prompt {
		margin: 0;
		line-height: 1.5;
	}

	.answer-card {
		grid-area: answer;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);

		@include layout.desktop-up {
			align-self: start;
			max-height: 100%;
			overflow-y: auto;
		}
	}

	.next-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3);
	}

	.next-button {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
		display: inline-flex;
		align-items: center;
		text-decoration: none;
	}

	// a keyboard hint is noise on touch
	.key-hint {
		display: none;
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);

		@media (hover: hover) and (pointer: fine) {
			display: inline;
		}
	}

	.puzzle-table {
		grid-area: table;
		min-width: 0;

		// no toolbar rail above it here, so the rim closes on every side.
		:global(.table-surface) {
			border-radius: var(--radius-lg);
		}

		@include layout.tablet-up {
			height: min(80dvh, 56rem);

			:global(.table-surface) {
				border-top-width: 10px;
			}
		}

		@include layout.desktop-up {
			height: auto;
			min-height: 0;
		}

		@include layout.phone-only {
			display: flex;
			flex-direction: column;
		}

		@include layout.phone-landscape {
			height: 100dvh;
		}
	}
</style>
