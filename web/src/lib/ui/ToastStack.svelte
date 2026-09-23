<script lang="ts">
	import Toast from './Toast.svelte';
	import type { ToastEntry } from './toasts';

	let { queue, onDismiss }: { queue: ToastEntry[]; onDismiss: (id: number) => void } = $props();
</script>

<div class="toast-stack">
	{#each queue as toast (toast.id)}
		<Toast
			message={toast.message}
			durationMs={toast.durationMs}
			onDismiss={() => onDismiss(toast.id)}
		/>
	{/each}
</div>

<style lang="scss">
	.toast-stack {
		position: fixed;
		top: var(--space-4);
		right: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-width: 20rem;
		z-index: var(--z-overlay);
	}
</style>
