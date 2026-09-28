<script lang="ts">
	import type { PracticeDifficulty } from '$lib/net/lobby';
	import { m } from '$lib/paraglide/messages.js';

	let {
		testId,
		positionLabel,
		difficulty,
		onCycle
	}: {
		testId: string;
		positionLabel: string;
		difficulty: PracticeDifficulty;
		onCycle: () => void;
	} = $props();

	const DIFFICULTY_LABEL: Record<PracticeDifficulty, string> = {
		easy: 'Easy',
		normal: 'Normal',
		impossible: 'Impossible'
	};
</script>

<div class="slot-column">
	<button
		type="button"
		class="seat-ring-slot"
		data-testid={testId}
		aria-label={m.practiceDifficultySlot_ariaLabel({
			position: positionLabel,
			difficulty: DIFFICULTY_LABEL[difficulty]
		})}
		onclick={onCycle}
	>
		<span>{DIFFICULTY_LABEL[difficulty]}</span>
	</button>
	<span class="slot-caption">{positionLabel}</span>
</div>

<style lang="scss">
	.slot-column {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
	}

	// same round-badge motif as SeatRingSlot/SeatPickerSlot's seat-ring-slot, sized up to fit a
	// difficulty word instead of a one-line seat status.
	.seat-ring-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 4.25rem;
		height: 4.25rem;
		padding: var(--space-1);
		border-radius: 50%;
		border: 1px solid var(--color-border);
		background: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-align: center;
		line-height: 1.1;
		cursor: pointer;

		&:hover {
			background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		}
	}

	.slot-caption {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}
</style>
