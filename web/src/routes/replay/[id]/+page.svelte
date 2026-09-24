<script lang="ts">
	import BackButton from '$lib/ui/BackButton.svelte';
</script>

<div class="replay-header">
	<BackButton label="Lobby" href="/" />
</div>
<h1>Replay</h1>

<style lang="scss">
	.replay-header {
		display: flex;
		margin: var(--space-4);
	}
</style>
