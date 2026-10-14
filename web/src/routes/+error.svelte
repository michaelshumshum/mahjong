<script lang="ts">
	import { page } from '$app/state';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';
</script>

<svelte:head>
	<title>{m.errorPage_pageTitle({ status: page.status })}</title>
</svelte:head>

<div class="error-header">
	<BackButton label={m.errorPage_backLabel()} href="/" />
</div>
<h1>{page.status}</h1>
<p>{page.status === 404 ? m.errorPage_notFound() : m.errorPage_generic()}</p>

<style lang="scss">
	.error-header {
		display: flex;
		margin: var(--space-4);
	}

	h1,
	p {
		margin-inline: var(--space-4);
	}
</style>
