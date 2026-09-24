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
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

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
