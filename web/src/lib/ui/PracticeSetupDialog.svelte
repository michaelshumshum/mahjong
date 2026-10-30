<script lang="ts">
	import ModalDialog from './ModalDialog.svelte';
	import { createPracticeTable } from '$lib/net/lobby';
	import { PRACTICE_DIFFICULTIES, type PracticeDifficulty } from '$lib/net/practice-difficulty';
	import { m } from '$lib/paraglide/messages.js';
	import PanelHeader from './PanelHeader.svelte';
	import PracticeDifficultySlot from './PracticeDifficultySlot.svelte';
	import CompassFelt from '$lib/table/CompassFelt.svelte';
	import { loadPracticeSetup, savePracticeSetup, type PracticeSetup } from './settings-storage';

	let { onCreated, onCancel }: { onCreated: (tableId: string) => void; onCancel: () => void } =
		$props();

	const TIER_LEGEND = [
		{ label: m.practiceDifficultySlot_easyLabel, blurb: m.practiceSetupDialog_easyBlurb },
		{ label: m.practiceDifficultySlot_normalLabel, blurb: m.practiceSetupDialog_normalBlurb },
		{ label: m.practiceDifficultySlot_expertLabel, blurb: m.practiceSetupDialog_expertBlurb },
		{
			label: m.practiceDifficultySlot_impossibleLabel,
			blurb: m.practiceSetupDialog_impossibleBlurb
		}
	];

	function nextDifficulty(current: PracticeDifficulty): PracticeDifficulty {
		return PRACTICE_DIFFICULTIES[
			(PRACTICE_DIFFICULTIES.indexOf(current) + 1) % PRACTICE_DIFFICULTIES.length
		];
	}

	// seats 1-3 only -- seat 0 is the human's own seat, never configured here. Offsets from your
	// own seat, clockwise, matching wind.ts's relativeSeat: 1 right, 2 across, 3 left.
	let difficulty = $state<PracticeSetup>(
		loadPracticeSetup() ?? { 1: 'normal', 2: 'normal', 3: 'normal' }
	);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	async function handleSubmit(): Promise<void> {
		submitting = true;
		error = null;
		try {
			const { table_id } = await createPracticeTable(difficulty);
			savePracticeSetup($state.snapshot(difficulty));
			onCreated(table_id);
		} catch {
			error = m.practiceSetupDialog_createErrorMessage();
			submitting = false;
		}
	}
</script>

<ModalDialog labelledby="practice-setup-heading" onCancel={() => !submitting && onCancel()}>
	<div class="practice-dialog" data-testid="practice-setup-dialog">
		<PanelHeader title={m.practiceSetupDialog_title()} titleId="practice-setup-heading" />
		<p class="practice-hint">{m.practiceSetupDialog_hint()}</p>

		<!-- Same ring arrangement as the real seat-selection screen (SeatRing/SeatPicker,
			docs/frontend.md's "Pre-game states") -- right/across/left are the bot seats this
			dialog configures; self is always the human seat, never one of them. -->
		<div class="seat-ring">
			<div class="seat-ring-pos seat-ring-pos--across">
				<PracticeDifficultySlot
					testId="practice-difficulty-across"
					positionLabel={m.practiceSetupDialog_positionAcross()}
					difficulty={difficulty[2]}
					onCycle={() => (difficulty[2] = nextDifficulty(difficulty[2]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--left">
				<PracticeDifficultySlot
					testId="practice-difficulty-left"
					positionLabel={m.practiceSetupDialog_positionLeft()}
					difficulty={difficulty[3]}
					onCycle={() => (difficulty[3] = nextDifficulty(difficulty[3]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--right">
				<PracticeDifficultySlot
					testId="practice-difficulty-right"
					positionLabel={m.practiceSetupDialog_positionRight()}
					difficulty={difficulty[1]}
					onCycle={() => (difficulty[1] = nextDifficulty(difficulty[1]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--self">
				<div class="seat-ring-slot seat-ring-slot--self">
					<span>{m.practiceSetupDialog_selfBadge()}</span>
				</div>
			</div>
			<div class="seat-ring-felt"><CompassFelt /></div>
		</div>

		<dl class="tier-legend" aria-label={m.practiceSetupDialog_tierLegendLabel()}>
			{#each TIER_LEGEND as tier (tier.label)}
				<div class="tier-row">
					<dt>{tier.label()}</dt>
					<dd>{tier.blurb()}</dd>
				</div>
			{/each}
		</dl>

		{#if error}
			<p class="practice-error">{error}</p>
		{/if}

		<div class="practice-actions">
			<button type="button" onclick={onCancel} disabled={submitting}
				>{m.practiceSetupDialog_cancelButton()}</button
			>
			<button
				type="button"
				class="practice-submit"
				data-testid="practice-start-submit"
				onclick={handleSubmit}
				disabled={submitting}
			>
				{submitting ? m.practiceSetupDialog_startingButton() : m.practiceSetupDialog_startButton()}
			</button>
		</div>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.practice-dialog {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-4);
		width: 100%;
		max-width: 24rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		text-align: center;
		@include buttons.panel-elevated;
	}

	.practice-hint {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	@include layout.seat-ring(4.5rem);

	// dealer isn't known until table construction, so this reads "you", not a wind letter --
	// plain bold text, matching SeatRingSlot's self treatment.
	.seat-ring-slot--self {
		color: var(--color-text);
		font-size: var(--font-size-sm);
		font-weight: 700;

		span {
			user-select: none;
		}
	}

	.tier-legend {
		display: grid;
		gap: var(--space-1);
		width: 100%;
		margin: 0;
		padding: var(--space-3);
		border-radius: var(--radius-sm);
		background: rgb(0 0 0 / 0.18);
		text-align: start;
		font-size: var(--font-size-sm);
	}

	.tier-row {
		display: grid;
		grid-template-columns: 6rem 1fr;
		gap: var(--space-2);

		dt {
			font-weight: 700;
		}

		dd {
			margin: 0;
			color: var(--color-text-muted);
		}
	}

	.practice-error {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.practice-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-3);
		width: 100%;

		button {
			@include buttons.btn-base(var(--space-4));
			@include buttons.btn-secondary;
		}

		.practice-submit {
			@include buttons.btn-primary;
		}
	}
</style>
