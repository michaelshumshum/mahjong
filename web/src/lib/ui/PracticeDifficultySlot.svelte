<script lang="ts">
	import { DIFFICULTY_LABEL, type PracticeDifficulty } from '$lib/net/practice-difficulty';
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
</script>

<button
	type="button"
	class="seat-ring-slot"
	data-testid={testId}
	aria-label={m.practiceDifficultySlot_ariaLabel({
		position: positionLabel,
		difficulty: DIFFICULTY_LABEL[difficulty]()
	})}
	onclick={onCycle}
>
	<span>{DIFFICULTY_LABEL[difficulty]()}</span>
</button>

<style lang="scss">
	// pill-button version of the table cards' open-seat treatment (TableCard's dashed pill,
	// made solid since this one carries a difficulty word and cycles on tap).
	.seat-ring-slot {
		padding: var(--space-1) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-pill);
		background: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--font-size-sm);
		font-weight: 600;
		white-space: nowrap;
		cursor: pointer;

		&:hover {
			border-color: var(--color-accent);
			background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		}

		span {
			overflow: hidden;
			text-overflow: ellipsis;
			user-select: none;
		}
	}
</style>
