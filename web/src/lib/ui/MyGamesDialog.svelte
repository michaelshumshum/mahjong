<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import DismissablePanel from './DismissablePanel.svelte';
	import MyGames from './MyGames.svelte';
	import PanelHeader from './PanelHeader.svelte';

	let { onClose }: { onClose: () => void } = $props();

	const uid = $props.id();
</script>

<DismissablePanel {onClose}>
	<section class="my-games-dialog" aria-labelledby="{uid}-heading" data-testid="my-games-dialog">
		<PanelHeader title={m.myGames_heading()} titleId="{uid}-heading" />
		<div class="body">
			<MyGames />
		</div>
	</section>
</DismissablePanel>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	// fixed height so "load more" grows the list, not the dialog
	.my-games-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(90vw, 34rem);
		height: min(40rem, calc(100dvh - var(--space-6)));
		padding: var(--space-5) var(--space-5) var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6) var(--space-6) var(--space-5);
		}
	}

	.my-games-dialog > :global(.panel-header) {
		padding-inline-end: var(--space-6);
	}

	.body {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin-inline: calc(-1 * var(--space-2));
		padding: var(--space-1) var(--space-2) var(--space-2);
	}
</style>
