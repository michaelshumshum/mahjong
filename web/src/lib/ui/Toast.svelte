<script lang="ts">
	import { scheduleAutoDismiss } from './toasts';

	let {
		message,
		durationMs = 4000,
		onDismiss
	}: { message: string; durationMs?: number; onDismiss: () => void } = $props();

	$effect(() => scheduleAutoDismiss(durationMs, onDismiss));
</script>

<div class="toast" role="status" data-duration-ms={durationMs}>
	<span class="message">{message}</span>
	<button type="button" class="dismiss" aria-label="Dismiss" onclick={onDismiss}>×</button>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.toast {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--color-surface-raised);
		color: var(--color-text);
		animation: toast-in 150ms ease-out;
		@include buttons.panel-elevated;
	}

	@media (prefers-reduced-motion: reduce) {
		.toast {
			animation: none;
		}
	}

	@keyframes toast-in {
		from {
			opacity: 0;
			transform: translateY(4px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	.message {
		flex: 1;
	}

	.dismiss {
		min-width: 44px;
		min-height: 44px;
		font-size: var(--font-size-lg);
		line-height: 1;
		cursor: pointer;
		padding: 0;
		@include buttons.btn-ghost;
	}

	.dismiss:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
