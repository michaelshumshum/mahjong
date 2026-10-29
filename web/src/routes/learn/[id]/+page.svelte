<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import ChevronRight from '@lucide/svelte/icons/chevron-right';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import AnswerPanel from '$lib/learn/AnswerPanel.svelte';
	import { grade } from '$lib/learn/grade';
	import { BAND_LABEL, nextLesson, previousLesson } from '$lib/learn/lessons';
	import { LESSON_TEXT, lessonTextParams } from '$lib/learn/lesson-text';
	import { loadProgress, saveAttempt } from '$lib/learn/progress';
	import { puzzleState } from '$lib/learn/puzzle-state';
	import type { Answer, GradeResult } from '$lib/learn/types';
	import { m } from '$lib/paraglide/messages.js';
	import CenterHub from '$lib/table/CenterHub.svelte';
	import { legalDiscardIds } from '$lib/table/legal-actions';
	import { viewFromClientState } from '$lib/table/live-view';
	import TableScene from '$lib/table/TableScene.svelte';
	import { tileIdToCode } from '$lib/table/tile-code';
	import type { OwnHandTile } from '$lib/table/view-types';
	import BackButton from '$lib/ui/BackButton.svelte';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';
	import { loadClientPrefs, DEFAULT_CLIENT_PREFS } from '$lib/ui/settings-storage';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();

	let lesson = $derived(data.lesson);
	let gameState = $derived(puzzleState(lesson));
	// the snapshot always seats you at 0, so the projection is never null.
	let live = $derived(viewFromClientState(gameState)!);
	let view = $derived(live.view);
	let text = $derived(LESSON_TEXT[lesson.text]);
	let params = $derived(lessonTextParams(lesson));
	let previous = $derived(previousLesson(lesson.id));
	let next = $derived(nextLesson(lesson.id));

	const discardMode = (loadClientPrefs() ?? DEFAULT_CLIENT_PREFS).discardMode;

	let result = $state<GradeResult | null>(null);
	let lastAnswer = $state<Answer | null>(null);
	let attempts = $state(0);
	let solvedBefore = $state(false);
	let guideFocus = $state<string | null>(null);
	$effect.pre(() => {
		const id = lesson.id;
		result = null;
		lastAnswer = null;
		attempts = 0;
		guideFocus = null;
		solvedBefore = loadProgress()[id]?.solved ?? false;
	});

	// a discard win: the claimed tile is the snapshot's last discard
	let claimedTile = $derived(
		lesson.kind === 'count_faan' && lesson.key.win_type === 'discard' && gameState.lastDiscard
			? tileIdToCode(gameState.lastDiscard.tileId)
			: null
	);

	let ownHandTiles = $derived.by((): OwnHandTile[] => {
		const tiles: OwnHandTile[] = live.ownHand.concealedIds.map((id) => ({
			key: `t-${id}`,
			code: tileIdToCode(id),
			tileId: id,
			drawn: false
		}));
		const drawnId = live.ownHand.drawnId;
		if (drawnId !== null) {
			tiles.push({
				key: `t-${drawnId}`,
				code: tileIdToCode(drawnId),
				tileId: drawnId,
				drawn: true
			});
		}
		return tiles;
	});

	let answersByDiscard = $derived(lesson.kind === 'best_discard' || lesson.kind === 'safe_discard');
	let discardableTileIds = $derived(
		answersByDiscard ? legalDiscardIds(gameState.legalActions) : new Set<number>()
	);

	function answer(given: Answer): void {
		result = grade(lesson, given).result;
		lastAnswer = given;
		attempts += 1;
		saveAttempt(lesson.id, result === 'correct');
	}

	function discard(tileId: number): void {
		if (lesson.kind !== 'best_discard' && lesson.kind !== 'safe_discard') return;
		answer({ kind: lesson.kind, tile: tileIdToCode(tileId) });
	}

	let solved = $derived(solvedBefore || result === 'correct');
</script>

<svelte:head>
	<title>{m.learn_lessonPageTitle({ title: text.title(params) })}</title>
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
	<div class="puzzle-page" data-testid="puzzle-page" data-kind={lesson.kind}>
		<nav class="puzzle-nav">
			<BackButton label={m.learn_indexLabel()} href="/learn" />
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
			</span>
		</nav>

		<section class="prompt-card" aria-labelledby="puzzle-title">
			<p class="meta">
				<span class="band">{BAND_LABEL[lesson.band]()}</span>
				{#if solved}
					<span class="solved" data-testid="puzzle-solved">
						<CircleCheck size={16} aria-hidden="true" />
						{m.learn_solvedMark()}
					</span>
				{/if}
			</p>
			<h1 id="puzzle-title">{text.title(params)}</h1>
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
					{discardMode}
					onDiscard={discard}
					holdLastDiscard={claimedTile !== null}
				/>
			{/key}
		</div>

		<section class="answer-card">
			<AnswerPanel
				{lesson}
				{discardMode}
				answer={lastAnswer}
				{result}
				{attempts}
				explanation={text.explain(params)}
				seatNames={gameState.names}
				{claimedTile}
				onAnswer={answer}
				onPatternSelect={(pattern) => (guideFocus = pattern)}
			/>
			{#if result === 'correct' && next}
				<a class="next-button" href="/learn/{next.id}" data-sfx="on" data-testid="answer-next"
					>{m.learn_nextLabel()}</a
				>
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

	.next-button {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
		display: inline-flex;
		align-items: center;
		align-self: flex-start;
		text-decoration: none;
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
