<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { accountSession } from '$lib/net/account-session.svelte';
	import AccountPanel from '$lib/ui/AccountPanel.svelte';

	const status = $derived(accountSession.state.status);
</script>

<svelte:head>
	<title>{m.profilePage_pageTitle()}</title>
</svelte:head>

<a class="back-link" data-sfx="on" href="/">← {m.profilePage_backLabel()}</a>
<h1>{m.profilePage_heading()}</h1>

{#if status === 'guest' || status === 'signedIn'}
	<section class="account-card">
		<AccountPanel />
	</section>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.back-link {
		display: inline-block;
		margin: var(--space-4);
		color: var(--color-text-muted);
		text-decoration: none;

		&:hover {
			color: var(--color-text);
		}
	}

	.account-card {
		max-width: 30rem;
		margin: var(--space-4);
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}
</style>
