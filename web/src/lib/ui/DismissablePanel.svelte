<script lang="ts">
	import type { Snippet } from 'svelte';
	import CloseButton from './CloseButton.svelte';

	let { onClose, children }: { onClose: () => void; children: Snippet } = $props();
</script>

<div class="panel-overlay">
	<div class="panel">
		<CloseButton onclick={onClose} />
		{@render children()}
	</div>
</div>

<style lang="scss">
	.panel-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.5);
		z-index: var(--z-modal);
		padding: var(--space-3);
	}

	// hugs whatever dialog content it wraps so the CloseButton it contains is positioned against
	// that panel's own corner, not the fullscreen scrim's.
	.panel {
		position: relative;
	}
</style>
