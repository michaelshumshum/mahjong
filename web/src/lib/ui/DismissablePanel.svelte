<script lang="ts">
	import type { Snippet } from 'svelte';
	import CloseButton from './CloseButton.svelte';
	import ModalDialog from './ModalDialog.svelte';

	let { onClose, label, children }: { onClose: () => void; label?: string; children: Snippet } =
		$props();
</script>

<ModalDialog onCancel={onClose} {label}>
	<div class="panel">
		<CloseButton onclick={onClose} />
		{@render children()}
	</div>
</ModalDialog>

<style lang="scss">
	// hugs whatever dialog content it wraps so the CloseButton it contains is positioned against
	// that panel's own corner, not the fullscreen scrim's.
	.panel {
		position: relative;
		max-height: calc(100vh - var(--space-6));
		max-width: calc(100vw - var(--space-6));
		overflow-y: auto;
		overflow-x: hidden;
	}
</style>
