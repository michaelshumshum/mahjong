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
	@use '$lib/styles/forms';

	// fixed height so "load more" grows the list, not the dialog
	.my-games-dialog {
		@include forms.dialog-panel(34rem, $dismissable: true);
		height: min(40rem, calc(100dvh - var(--space-6)));
	}

	.body {
		@include forms.dialog-scroll-body;
		padding: var(--space-1) var(--space-2) var(--space-2);
	}
</style>
