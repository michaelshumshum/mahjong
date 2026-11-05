<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { accountSession } from '$lib/net/account-session.svelte';
	import AccountPanel from '$lib/ui/AccountPanel.svelte';
	import AccountSettings from '$lib/ui/AccountSettings.svelte';
	import MyGames from '$lib/ui/MyGames.svelte';

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
{#if accountSession.user}
	<section class="account-card" aria-labelledby="account-settings-heading">
		<h2 id="account-settings-heading">{m.accountSettings_heading()}</h2>
		<AccountSettings user={accountSession.user} />
	</section>
	<section class="account-card" aria-labelledby="my-games-heading">
		<h2 id="my-games-heading">{m.myGames_heading()}</h2>
		<MyGames />
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

		h2 {
			margin: 0 0 var(--space-4);
			font-size: var(--font-size-lg);
		}
	}
</style>
