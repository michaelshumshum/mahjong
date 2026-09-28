<script lang="ts">
	import ToastStack from '$lib/ui/ToastStack.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';
	import { m } from '$lib/paraglide/messages.js';

	// a small local queue built from toasts.ts's pure helpers, proving out queuing/dismiss together.
	let toastQueue = $state<ToastEntry[]>([]);
	function pushToast(message: string, durationMs?: number): void {
		toastQueue = [...toastQueue, createToast(message, durationMs)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}
</script>

<h2>{m.toastDemo_heading()}</h2>
<p class="hint">
	{m.toastDemo_hint()}
</p>
<div class="toast-controls">
	<button type="button" onclick={() => pushToast(m.toastDemo_reconnectingMessage())}
		>{m.toastDemo_pushReconnectingButton()}</button
	>
	<button type="button" onclick={() => pushToast(m.toastDemo_copiedMessage(), 1500)}>
		{m.toastDemo_pushCopiedButton()}
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
