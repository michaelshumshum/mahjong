<script lang="ts" module>
	export type CoachTarget = 'hand' | 'discards' | null;
</script>

<script lang="ts">
	import type { DiscardMode } from './client-prefs';
	import { m } from '$lib/paraglide/messages.js';

	let {
		discardMode,
		onStepChange,
		onDone
	}: {
		discardMode: DiscardMode;
		// lets the table outline whatever the current tip points at.
		onStepChange: (target: CoachTarget) => void;
		onDone: () => void;
	} = $props();

	let steps = $derived([
		{
			target: 'hand' as const,
			text:
				discardMode === 'two-step' ? m.coachMarks_discardTwoStep() : m.coachMarks_discardOneTap()
		},
		{ target: 'discards' as const, text: m.coachMarks_lastDiscard() },
		{ target: null, text: m.coachMarks_claims() }
	]);

	let index = $state(0);
	let step = $derived(steps[index]);
	let isLast = $derived(index === steps.length - 1);

	$effect(() => {
		onStepChange(step.target);
	});

	function next(): void {
		if (isLast) onDone();
		else index += 1;
	}
</script>

<div
	class="coach-mark"
	role="region"
	aria-label={m.coachMarks_regionLabel()}
	aria-live="polite"
	data-testid="coach-mark"
>
	{#key index}
		<p class="coach-counter">{m.coachMarks_stepCounter({ n: index + 1, total: steps.length })}</p>
		<p class="coach-text">{step.text}</p>
	{/key}
	<div class="coach-actions">
		<button type="button" class="coach-skip" data-testid="coach-skip" onclick={onDone}
			>{m.coachMarks_skipButton()}</button
		>
		<button type="button" class="coach-next" data-testid="coach-next" onclick={next}
			>{isLast ? m.coachMarks_doneButton() : m.coachMarks_nextButton()}</button
		>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';

	.coach-mark {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: min(22rem, calc(100vw - var(--space-6)));
		padding: var(--space-3) var(--space-4);
		border: 1px solid color-mix(in srgb, var(--color-brass) 60%, var(--color-border));
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		box-shadow: 0 12px 28px -8px rgb(10 4 2 / 0.75);

		@include a11y.motion-ok {
			animation: coach-in var(--dur-3) var(--ease-out) both;
		}
	}

	@keyframes coach-in {
		from {
			opacity: 0;
			transform: translateY(-8px);
		}
	}

	.coach-counter {
		margin: 0;
		color: var(--color-brass);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.coach-text {
		margin: 0;
		font-size: var(--font-size-base);
		line-height: 1.4;
	}

	.coach-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-2);

		button {
			min-height: var(--tap-target-min);
			padding: var(--space-1) var(--space-4);
			font: inherit;
			font-size: var(--font-size-sm);
			cursor: pointer;
		}
	}

	.coach-skip {
		@include buttons.btn-ghost;
	}

	.coach-next {
		@include buttons.btn-secondary;
	}
</style>
