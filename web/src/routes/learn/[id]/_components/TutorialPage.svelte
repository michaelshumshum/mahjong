<script lang="ts">
	import { untrack } from 'svelte';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import RotateCcw from '@lucide/svelte/icons/rotate-ccw';
	import type { ClaimOption, Seat } from '$lib/game/types';
	import type { Highlight, Tutorial } from '$lib/learn/generated/lessons';
	import { LessonPlayer, type TutorialIntent } from '$lib/learn/lesson-player.svelte';
	import { TUTORIAL_TEXT } from '$lib/learn/lesson-text';
	import { loadProgress } from '$lib/learn/progress';
	import TutorialCoach from '$lib/learn/TutorialCoach.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import CenterHub from '$lib/table/CenterHub.svelte';
	import {
		findRawClaimOption,
		legalClaimOptions,
		legalDeclareOptions,
		legalDiscardIds
	} from '$lib/table/legal-actions';
	import { meldToView, ownHandTiles as handTiles, viewFromClientState } from '$lib/table/live-view';
	import TableScene from '$lib/table/TableScene.svelte';
	import type { CoachTarget, DeclareOption } from '$lib/table/view-types';
	import BackButton from '$lib/ui/BackButton.svelte';
	import ClaimDialog from '$lib/ui/ClaimDialog.svelte';
	import CoachCard from '$lib/ui/CoachCard.svelte';
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';
	import ModalDialog from '$lib/ui/ModalDialog.svelte';
	import { motionMs } from '$lib/ui/motion';
	import {
		loadClientPrefs,
		savePracticeSetup,
		DEFAULT_CLIENT_PREFS,
		type PracticeSetup
	} from '$lib/ui/settings-storage';
	import { goto } from '$app/navigation';
	import { createPracticeTable } from '$lib/net/lobby';

	let { tutorial }: { tutorial: Tutorial } = $props();

	// the other seats' moves, one at a time, so a player can follow them.
	const AUTO_STEP_MS = 700;

	// one player per tutorial: +page.svelte keys this component by id.
	const initial = untrack(() => tutorial);
	const text = TUTORIAL_TEXT[initial.text];
	const savedStep = loadProgress()[initial.id]?.step ?? null;
	let solved = $state(loadProgress()[initial.id]?.solved ?? false);
	let offerResume = $state(savedStep !== null);

	const player = new LessonPlayer(initial, {
		autoDelayMs: motionMs(AUTO_STEP_MS),
		persist: true,
		onComplete: () => (solved = true)
	});
	$effect(() => () => player.destroy());

	const discardMode = (loadClientPrefs() ?? DEFAULT_CLIENT_PREFS).discardMode;

	// a narrate tip's highlight onto the table: a region outline, or for a claim, the claimable
	// discard held in brass.
	const HIGHLIGHT: Record<Highlight, { coach: CoachTarget | null; holdLastDiscard: boolean }> = {
		hand: { coach: 'hand', holdLastDiscard: false },
		melds: { coach: 'melds', holdLastDiscard: false },
		discards: { coach: 'discards', holdLastDiscard: false },
		wall: { coach: 'wall', holdLastDiscard: false },
		hub: { coach: 'hub', holdLastDiscard: false },
		claim: { coach: null, holdLastDiscard: true }
	};

	// the scene always seats you at 0, so the projection is never null.
	let live = $derived(viewFromClientState(player.state)!);
	let view = $derived(live.view);
	let ownHandTiles = $derived(handTiles(live.ownHand));

	let step = $derived(player.step);
	let expect = $derived(step?.kind === 'expect' ? step : null);
	let highlight = $derived(
		step?.kind === 'narrate' && step.highlight ? HIGHLIGHT[step.highlight] : null
	);
	// while the other seats play, the last tip stays up.
	let shownText = $derived.by(() => {
		for (let i = player.index; i >= 0; i--) {
			const s = tutorial.steps[i];
			if (s.kind !== 'auto') return s.text;
		}
		return null;
	});
	let tip = $derived(shownText ? text.steps[shownText]() : '');

	let discardableTileIds = $derived(
		expect ? legalDiscardIds(player.state.legalActions) : new Set<number>()
	);
	let declareOptions = $derived(
		expect
			? legalDeclareOptions(player.state.legalActions, {
					win: () => act({ kind: 'declare_win' }),
					concealedKong: (tiles) => act({ kind: 'declare_concealed_kong', tiles }),
					addedKong: (tiles) => act({ kind: 'declare_added_kong', tiles })
				})
			: ([] as DeclareOption[])
	);
	let claimOptions = $derived(expect ? legalClaimOptions(view.claimWindow) : null);

	let seatNames = $derived(
		Object.fromEntries(view.seats.map((s) => [s.seat, s.name])) as Record<Seat, string>
	);
	let haloTurn = $derived(view.handResult ? -1 : view.turn);

	// a wrong discard never gets its echo, so the scene remounts to drop the pending tile.
	let sceneKey = $state(0);
	function act(intent: TutorialIntent): void {
		if (!player.act(intent) && intent.kind === 'discard') sceneKey += 1;
	}

	function chooseClaim(option: ClaimOption): void {
		const raw = findRawClaimOption(player.state.claimOffer?.options ?? null, option);
		act({ kind: 'claim', choice: option.kind, tiles: raw?.tiles as number[] | undefined });
	}

	function resume(): void {
		offerResume = false;
		if (savedStep !== null) player.goTo(savedStep);
	}

	function restart(): void {
		offerResume = false;
		sceneKey += 1;
		player.restart();
	}

	let guideFocus = $state<string | null>(null);

	const EASY_PRACTICE: PracticeSetup = { 1: 'easy', 2: 'easy', 3: 'easy' };
	let practicePending = $state(false);
	let practiceFailed = $state(false);

	// the practice dialog's own create path, all three bots easy; saved as the last setup so the
	// game-end "Play again" repeats it.
	async function practiceEasy(): Promise<void> {
		practicePending = true;
		practiceFailed = false;
		try {
			const { table_id } = await createPracticeTable(EASY_PRACTICE);
			savePracticeSetup(EASY_PRACTICE);
			await goto(`/table/${encodeURIComponent(table_id)}?practice=1`);
		} catch {
			practiceFailed = true;
			practicePending = false;
		}
	}
</script>

<svelte:head>
	<title>{m.learn_lessonPageTitle({ title: text.title() })}</title>
</svelte:head>

{#snippet hub()}
	<CenterHub
		prevailing={view.prevailing}
		handNo={view.handNo}
		dealer={view.dealer}
		turn={haloTurn as Seat}
		you={view.you}
		wallCount={view.wallCount}
		minFaan={player.state.ruleset?.min_faan ?? null}
		turnDurationMs={view.turnDurationMs}
	/>
{/snippet}

<div class="tutorial-page" data-testid="tutorial-page" data-step={player.index}>
	<nav class="tutorial-nav">
		<BackButton label={m.learn_indexLabel()} href="/learn" />
		<button type="button" class="restart" data-testid="tutorial-restart" onclick={restart}>
			<RotateCcw size={16} aria-hidden="true" />
			<span>{m.learn_tutorialRestart()}</span>
		</button>
	</nav>

	<section class="tutorial-side" aria-labelledby="tutorial-title">
		<p class="meta">
			<span>{m.learn_tutorialLabel()}</span>
			{#if solved}
				<span class="solved" data-testid="tutorial-solved">
					<CircleCheck size={16} aria-hidden="true" />
					{m.learn_solvedMark()}
				</span>
			{/if}
		</p>
		<h1 id="tutorial-title">{text.title()}</h1>

		{#if offerResume && savedStep !== null}
			<CoachCard
				label={m.learn_tutorialCoachLabel()}
				counter={m.learn_tutorialLabel()}
				testid="tutorial-resume"
			>
				<p class="coach-text">
					{m.learn_tutorialResumePrompt({
						n: tutorial.steps.slice(0, savedStep + 1).filter((s) => s.kind !== 'auto').length
					})}
				</p>
				{#snippet actions()}
					<button
						type="button"
						class="coach-skip"
						data-testid="tutorial-start-over"
						onclick={restart}>{m.learn_tutorialStartOver()}</button
					>
					<button
						type="button"
						class="coach-next"
						data-testid="tutorial-resume-button"
						onclick={resume}>{m.learn_tutorialResume()}</button
					>
				{/snippet}
			</CoachCard>
		{:else}
			<TutorialCoach
				step={player.waitingNumber}
				total={player.waitingCount}
				{tip}
				move={expect !== null}
				wrongMoves={claimOptions ? 0 : player.wrongMoves}
				busy={player.busy}
				canBack={player.previousWaiting !== null && !player.busy}
				canNext={step?.kind === 'narrate'}
				onBack={() => player.back()}
				onNext={() => player.next()}
				end={player.isLast ? tutorialEnd : undefined}
			>
				{#if player.isLast && view.handResult?.outcome === 'win'}
					<div class="result" data-testid="faan-breakdown">
						<FaanBreakdown
							winner={view.handResult.winner as Seat}
							{seatNames}
							heading={m.learn_faanBreakdownHeading()}
							winningHand={view.handResult.winningHand ?? []}
							melds={player.state.melds[0].map(meldToView)}
							patterns={view.handResult.patterns ?? []}
							totalFaan={view.handResult.totalFaan ?? 0}
							payments={view.handResult.payments ?? {}}
							onPatternSelect={(pattern) => (guideFocus = pattern)}
						/>
					</div>
				{/if}
				{#if practiceFailed}
					<p class="practice-error" role="alert">{m.learn_tutorialPracticeError()}</p>
				{/if}
			</TutorialCoach>
		{/if}
	</section>

	<div class="tutorial-table">
		{#key sceneKey}
			<TableScene
				{view}
				spectating={false}
				isMock={false}
				turn={haloTurn}
				{hub}
				{ownHandTiles}
				{discardableTileIds}
				{declareOptions}
				{discardMode}
				onDiscard={(tileId) => act({ kind: 'discard', tileId })}
				holdLastDiscard={highlight?.holdLastDiscard ?? false}
				coach={offerResume ? null : (highlight?.coach ?? null)}
			/>
		{/key}
	</div>
</div>

{#snippet tutorialEnd()}
	<a class="coach-skip" href="/learn" data-sfx="on" data-testid="tutorial-to-puzzles"
		>{m.learn_tutorialBackToPuzzles()}</a
	>
	<button
		type="button"
		class="coach-next"
		data-testid="tutorial-practice"
		disabled={practicePending}
		onclick={practiceEasy}>{m.learn_tutorialPractice()}</button
	>
{/snippet}

{#if claimOptions && !offerResume}
	<ModalDialog testid="claim-overlay" label={m.claimDialog_ariaLabel()} placement="sheet">
		<div class="tutorial-claim">
			<div class="claim-tip">
				<p data-testid="tutorial-claim-tip">{tip}</p>
				{#if player.wrongMoves > 0}
					{#key player.wrongMoves}
						<p class="claim-wrong" role="status" data-testid="tutorial-hint">
							{m.learn_tutorialWrongMove()}
						</p>
					{/key}
				{/if}
			</div>
			<ClaimDialog
				discardTile={view.claimWindow?.tile ?? null}
				discarderName={view.claimWindow ? view.seats[view.claimWindow.sourceSeat].name : null}
				options={claimOptions}
				durationMs={null}
				onChoose={chooseClaim}
			/>
		</div>
	</ModalDialog>
{/if}

{#if guideFocus !== null}
	<GuideDialog
		onClose={() => (guideFocus = null)}
		tableRules={player.state.ruleset}
		tablePreset={player.state.rulesetPreset}
		focusPattern={guideFocus}
	/>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.tutorial-page {
		display: grid;
		grid-template-areas: 'nav' 'side' 'table';
		grid-template-columns: minmax(0, 1fr);
		gap: var(--space-3);
		padding: var(--space-4);

		@include layout.desktop-up {
			grid-template-areas: 'nav nav' 'table side';
			grid-template-columns: minmax(0, 1fr) 24rem;
			grid-template-rows: auto minmax(0, 1fr);
			height: 100dvh;
			padding: var(--space-4) var(--space-5);
		}
	}

	.tutorial-nav {
		grid-area: nav;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
	}

	.restart {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-ghost;
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}

	.tutorial-side {
		grid-area: side;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;

		h1 {
			margin: 0 0 var(--space-1);
			font-size: var(--font-size-xl);
		}

		// the tip card fills the column here, not the floating width it has over the table.
		:global(.coach-mark) {
			width: 100%;
		}

		@include layout.desktop-up {
			overflow-y: auto;
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

	.tutorial-table {
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

	.practice-error {
		margin: 0;
		color: var(--color-negative);
		font-size: var(--font-size-sm);
	}

	.tutorial-claim {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		width: min(28rem, 100%);
	}

	.claim-tip {
		width: 100%;
		padding: var(--space-2) var(--space-4);
		border: 1px solid color-mix(in srgb, var(--color-brass) 60%, var(--color-border));
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);

		p {
			margin: 0;
			line-height: 1.4;
		}
	}

	.claim-tip .claim-wrong {
		margin-top: var(--space-1);
		color: var(--color-negative);
		font-weight: 600;
	}
</style>
