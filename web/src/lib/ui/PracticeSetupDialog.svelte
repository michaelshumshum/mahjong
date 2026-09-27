<script lang="ts">
	import {
		createTable,
		PRACTICE_DIFFICULTY_TO_TIER,
		type PracticeDifficulty
	} from '$lib/net/lobby';
	import PanelHeader from './PanelHeader.svelte';
	import PracticeDifficultySlot from './PracticeDifficultySlot.svelte';

	let { onCreated, onCancel }: { onCreated: (tableId: string) => void; onCancel: () => void } =
		$props();

	const DIFFICULTY_CYCLE: PracticeDifficulty[] = ['easy', 'normal', 'impossible'];

	function nextDifficulty(current: PracticeDifficulty): PracticeDifficulty {
		return DIFFICULTY_CYCLE[(DIFFICULTY_CYCLE.indexOf(current) + 1) % DIFFICULTY_CYCLE.length];
	}

	// seats 1-3 only -- seat 0 is the human's own seat (this route's existing seat-picker flow),
	// never configured here. Offsets from your own seat, clockwise, matching
	// mock-game-state.ts's relativeSeat: 1 right, 2 across, 3 left.
	let difficulty = $state<Record<1 | 2 | 3, PracticeDifficulty>>({
		1: 'normal',
		2: 'normal',
		3: 'normal'
	});
	let submitting = $state(false);
	let error = $state<string | null>(null);

	async function handleSubmit(): Promise<void> {
		submitting = true;
		error = null;
		try {
			const { table_id } = await createTable({
				practice: true,
				bot_tiers: {
					1: PRACTICE_DIFFICULTY_TO_TIER[difficulty[1]],
					2: PRACTICE_DIFFICULTY_TO_TIER[difficulty[2]],
					3: PRACTICE_DIFFICULTY_TO_TIER[difficulty[3]]
				}
			});
			onCreated(table_id);
		} catch {
			error = "Couldn't start a practice table — try again.";
			submitting = false;
		}
	}
</script>

<div class="panel-overlay">
	<div
		class="practice-dialog"
		role="dialog"
		aria-modal="true"
		aria-labelledby="practice-setup-heading"
	>
		<PanelHeader title="Practice vs Bots" titleId="practice-setup-heading" />
		<p class="practice-hint">Tap a seat to cycle its bot's difficulty.</p>

		<!-- Same ring arrangement as the real seat-selection screen (SeatRing/SeatPicker,
			docs/03-frontend.md's "Pre-game states") -- right/across/left are the bot seats this
			dialog configures; self is always the human seat, never one of them. -->
		<div class="seat-ring">
			<div class="seat-ring-pos seat-ring-pos--across">
				<PracticeDifficultySlot
					positionLabel="Across"
					difficulty={difficulty[2]}
					onCycle={() => (difficulty[2] = nextDifficulty(difficulty[2]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--left">
				<PracticeDifficultySlot
					positionLabel="Left opponent"
					difficulty={difficulty[3]}
					onCycle={() => (difficulty[3] = nextDifficulty(difficulty[3]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--right">
				<PracticeDifficultySlot
					positionLabel="Right opponent"
					difficulty={difficulty[1]}
					onCycle={() => (difficulty[1] = nextDifficulty(difficulty[1]))}
				/>
			</div>
			<div class="seat-ring-pos seat-ring-pos--self">
				<div class="slot-column">
					<div class="seat-ring-slot seat-ring-slot--self"><span>You</span></div>
					<span class="slot-caption">Your seat</span>
				</div>
			</div>
		</div>

		{#if error}
			<p class="practice-error">{error}</p>
		{/if}

		<div class="practice-actions">
			<button type="button" onclick={onCancel} disabled={submitting}>Cancel</button>
			<button type="button" class="practice-submit" onclick={handleSubmit} disabled={submitting}>
				{submitting ? 'Starting…' : 'Start'}
			</button>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

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

	// same geometry as SeatRing/SeatPicker's seat-ring (docs/03-frontend.md's "Pre-game
	// states"), sized up since each slot here carries a difficulty word + caption, not just a
	// one-line seat status.
	.seat-ring {
		display: grid;
		grid-template-areas:
			'.      across .'
			'left   .      right'
			'.      self   .';
		grid-template-columns: repeat(3, 5.5rem);
		grid-template-rows: repeat(3, 4.75rem);
		gap: var(--space-1);
		place-items: center;
	}

	.seat-ring-pos--across {
		grid-area: across;
	}

	.seat-ring-pos--left {
		grid-area: left;
	}

	.seat-ring-pos--right {
		grid-area: right;
	}

	.seat-ring-pos--self {
		grid-area: self;
	}

	.slot-column {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
	}

	// dealer isn't known until table construction, so this reads "you", not a wind letter --
	// matching SeatRingSlot's self=true treatment (accent-highlighted, non-interactive).
	.seat-ring-slot--self {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 4.25rem;
		height: 4.25rem;
		border-radius: 50%;
		border: 1px solid var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 16%, transparent);
		color: var(--color-text);
		font-size: var(--font-size-sm);
		font-weight: 600;
	}

	.slot-caption {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
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
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-4);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-secondary;
		}

		.practice-submit {
			@include buttons.btn-primary;
		}
	}
</style>
