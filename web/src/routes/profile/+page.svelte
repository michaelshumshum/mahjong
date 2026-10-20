<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
</script>

<svelte:head>
	<title>{m.profilePage_pageTitle()}</title>
</svelte:head>

<a class="back-link" data-sfx="on" href="/">← {m.profilePage_backLabel()}</a>
<h1>{m.profilePage_heading()}</h1>

<style lang="scss">
	.back-link {
		display: inline-block;
		margin: var(--space-4);
		color: var(--color-text-muted);
		text-decoration: none;

		&:hover {
			color: var(--color-text);
		}
	}
</style>
