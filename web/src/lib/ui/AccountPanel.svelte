<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { accountSession } from '$lib/net/account-session.svelte';
	import GoogleSignInButton from './GoogleSignInButton.svelte';
	import LegalLinks from './LegalLinks.svelte';
</script>

<!-- a signed-in player's account lives in AccountDialog -->
{#if accountSession.state.status === 'guest'}
	<div class="account-panel" data-testid="account-panel">
		<p class="blurb">{m.accountPanel_guestBlurb()}</p>
		<GoogleSignInButton />
		<p class="blurb">{m.accountPanel_termsNote()}</p>
		<LegalLinks />
	</div>
{/if}

<style lang="scss">
	.account-panel {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-3);
	}

	.blurb {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}
</style>
