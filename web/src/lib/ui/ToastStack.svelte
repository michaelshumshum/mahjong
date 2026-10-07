<script lang="ts">
	import Toast from './Toast.svelte';
	import { TOP_LAYER_EVENT, topmostDialog } from './ModalDialog.svelte';
	import type { ToastEntry } from './toasts';

	let { queue, onDismiss }: { queue: ToastEntry[]; onDismiss: (id: number) => void } = $props();

	let homeEl: HTMLDivElement | undefined = $state();
	let stackEl: HTMLDivElement | undefined = $state();

	// a modal <dialog> makes everything outside it inert (unclickable, not announced) and paints
	// above any z-index, so the stack lives inside the topmost open dialog while one is up.
	$effect(() => {
		const home = homeEl;
		const stack = stackEl;
		if (!home || !stack) return;
		const place = () => {
			const target = topmostDialog() ?? home;
			if (stack.parentNode !== target) target.append(stack);
		};
		place();
		window.addEventListener(TOP_LAYER_EVENT, place);
		return () => {
			window.removeEventListener(TOP_LAYER_EVENT, place);
			stack.remove();
		};
	});
</script>

<div class="toast-home" bind:this={homeEl}>
	<div class="toast-stack" bind:this={stackEl}>
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
		// above --z-modal: a toast (e.g. a rejected intent) must stay legible over an open dialog.
		z-index: var(--z-toast);
	}
</style>
