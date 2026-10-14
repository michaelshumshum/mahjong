<script lang="ts">
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';
</script>

<svelte:head>
	<title>{m.replayPage_pageTitle()}</title>
</svelte:head>

<div class="replay-header">
	<BackButton label={m.replayPage_backLabel()} href="/" />
</div>
<h1>{m.replayPage_heading()}</h1>

<style lang="scss">
	.replay-header {
		display: flex;
		margin: var(--space-4);
	}
</style>
