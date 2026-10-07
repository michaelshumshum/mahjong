<script lang="ts">
	import Toast from './Toast.svelte';
	import { followTopmostDialog } from './ModalDialog.svelte';
	import type { ToastEntry } from './toasts';

	let { queue, onDismiss }: { queue: ToastEntry[]; onDismiss: (id: number) => void } = $props();
</script>

<!-- the stack moves into an open modal (followTopmostDialog); this wrapper is its way home. -->
<div class="toast-home">
	<div class="toast-stack" {@attach followTopmostDialog}>
		{#each queue as toast (toast.id)}
			<Toast
				message={toast.message}
				durationMs={toast.durationMs}
				severity={toast.severity}
				onDismiss={() => onDismiss(toast.id)}
			/>
		{/each}
	</div>
</div>

<style lang="scss">
	.toast-home {
		display: contents;
	}

	.toast-stack {
		position: fixed;
		top: var(--space-4);
		right: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-width: 20rem;
		z-index: var(--z-toast);
	}
</style>
