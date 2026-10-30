<script lang="ts">
	import type { Snippet } from 'svelte';

	// the tip card shared by the practice coach marks and the learn tutorial: a counter, the tip
	// (announced politely as it changes) and the caller's buttons.
	let {
		label,
		counter,
		testid,
		children,
		actions
	}: {
		label: string;
		counter: string;
		testid?: string;
		children: Snippet;
		actions: Snippet;
	} = $props();
</script>

<div class="coach-mark" role="region" aria-label={label} data-testid={testid}>
	<div class="coach-body" aria-live="polite">
		<p class="coach-counter">{counter}</p>
		{@render children()}
	</div>
	<div class="coach-actions">
		{@render actions()}
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

	.coach-body {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.coach-counter {
		margin: 0;
		color: var(--color-brass);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.coach-body :global(.coach-text) {
		margin: 0;
		font-size: var(--font-size-base);
		line-height: 1.4;
	}

	.coach-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: flex-end;
		gap: var(--space-2);

		:global(button),
		:global(a) {
			display: inline-flex;
			align-items: center;
			min-height: var(--tap-target-min);
			padding: var(--space-1) var(--space-4);
			font: inherit;
			font-size: var(--font-size-sm);
			text-decoration: none;
			cursor: pointer;
		}

		:global(.coach-skip) {
			@include buttons.btn-ghost;
		}

		:global(.coach-next) {
			@include buttons.btn-secondary;
		}
	}
</style>
