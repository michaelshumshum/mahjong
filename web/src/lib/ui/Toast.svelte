<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { scheduleAutoDismiss } from './auto-close';
	import type { ToastSeverity } from './toasts';

	let {
		message,
		durationMs = 4000,
		severity = 'info',
		onDismiss
	}: {
		message: string;
		durationMs?: number;
		severity?: ToastSeverity;
		onDismiss: () => void;
	} = $props();

	$effect(() => scheduleAutoDismiss(durationMs, onDismiss));

	// text glyphs, not an icon asset -- one more thing colourblind-safe like the dragon glyphs.
	const ICON: Record<ToastSeverity, string> = { info: 'ⓘ', warn: '▲', error: '⛔' };
</script>

<div
	class="toast toast--{severity}"
	role={severity === 'error' ? 'alert' : 'status'}
	data-duration-ms={durationMs}
>
	<span class="icon" aria-hidden="true">{ICON[severity]}</span>
	<span class="message">{message}</span>
	<button type="button" class="dismiss" aria-label={m.toast_dismissLabel()} onclick={onDismiss}
		>×</button
	>
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';

	.toast {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3);
		background: var(--color-surface-raised);
		color: var(--color-text);
		border-inline-start: 3px solid var(--toast-accent, var(--color-border));
		@include buttons.panel-elevated;
		@include a11y.motion-ok {
			animation: toast-in var(--dur-1) var(--ease-out);
		}
	}

	// severity sets one accent custom property the rule above reads -- info stays the neutral
	// default border (no --toast-accent override).
	.toast--warn {
		--toast-accent: var(--color-status-error);
	}

	.toast--error {
		--toast-accent: var(--color-accent-on-dark);
	}

	.toast .icon {
		color: var(--toast-accent, var(--color-text-muted));
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
		min-width: var(--tap-target-min);
		min-height: var(--tap-target-min);
		font-size: var(--font-size-lg);
		line-height: 1;
		cursor: pointer;
		padding: 0;
		@include buttons.btn-ghost;
	}
</style>
