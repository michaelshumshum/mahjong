<script lang="ts">
	import ToastStack from '$lib/ui/ToastStack.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';

	// a small local queue built from toasts.ts's pure helpers, proving out queuing/dismiss together.
	let toastQueue = $state<ToastEntry[]>([]);
	function pushToast(message: string, durationMs?: number): void {
		toastQueue = [...toastQueue, createToast(message, durationMs)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}
</script>

<h2>Toast demo</h2>
<p class="hint">
	Generic transient notifications, queued locally with toasts.ts's pure helpers. Auto-dismiss is a
	one-shot timer per toast (not a JS ticker); dismiss manually with the × button.
</p>
<div class="toast-controls">
	<button type="button" onclick={() => pushToast('Reconnecting…')}>Push "Reconnecting…"</button>
	<button type="button" onclick={() => pushToast('Copied to clipboard', 1500)}>
		Push "Copied" (1.5s)
	</button>
</div>
<ToastStack queue={toastQueue} onDismiss={dismissToast} />

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.toast-controls {
		display: flex;
		gap: var(--space-3);
		margin-bottom: var(--space-4);
	}
</style>
