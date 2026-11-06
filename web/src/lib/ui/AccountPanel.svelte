<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { signOut } from '$lib/net/account';
	import { accountSession } from '$lib/net/account-session.svelte';
	import GoogleSignInButton from './GoogleSignInButton.svelte';
	import LegalLinks from './LegalLinks.svelte';

	// settings links to /profile's account settings; /profile itself doesn't
	let { manageLink = false }: { manageLink?: boolean } = $props();

	let busy = $state(false);
	let error = $state<string | null>(null);

	async function handleSignOut(): Promise<void> {
		busy = true;
		error = null;
		try {
			await signOut();
			accountSession.setUser(null);
		} catch {
			error = m.accountPanel_signOutError();
		} finally {
			busy = false;
		}
	}
</script>

{#if accountSession.state.status === 'signedIn'}
	<div class="account-panel" data-testid="account-panel">
		<p class="who">
			{m.accountPanel_signedInAs({ name: accountSession.state.user.display_name })}
		</p>
		{#if manageLink}
			<a class="manage" href="/profile" data-testid="account-manage">
				{m.accountPanel_manage()}
			</a>
		{/if}
		<button
			type="button"
			class="sign-out"
			data-testid="account-sign-out"
			disabled={busy}
			onclick={handleSignOut}
		>
			{m.accountPanel_signOut()}
		</button>
		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}
	</div>
{:else if accountSession.state.status === 'guest'}
	<div class="account-panel" data-testid="account-panel">
		<p class="blurb">{m.accountPanel_guestBlurb()}</p>
		<GoogleSignInButton />
		<p class="blurb">{m.accountPanel_termsNote()}</p>
		<LegalLinks />
	</div>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.account-panel {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
	}

	p {
		margin: 0;
	}

	.who {
		font-weight: 600;
	}

	.blurb {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.sign-out {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}

	.manage {
		color: var(--color-accent-on-dark);
		font-size: var(--font-size-sm);
	}

	.error {
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}
</style>
