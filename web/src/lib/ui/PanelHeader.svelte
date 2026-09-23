<script lang="ts">
	let {
		title,
		badge,
		titleId
	}: {
		title: string;
		badge?: string;
		titleId?: string;
	} = $props();
</script>

<header class="panel-header">
	<h2 id={titleId}>{title}</h2>
	{#if badge}
		<span class="panel-badge">{badge}</span>
	{/if}
</header>

<style lang="scss">
	@use '$lib/styles/forms';

	.panel-header {
		@include forms.panel-header;
	}

	h2 {
		@include forms.panel-title;
	}

	.panel-badge {
		@include forms.panel-badge;
	}
</style>
