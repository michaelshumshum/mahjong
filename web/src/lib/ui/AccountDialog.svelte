<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import type { Me } from '$lib/net/account';
	import AccountSettings from './AccountSettings.svelte';
	import Avatar from './Avatar.svelte';
	import DismissablePanel from './DismissablePanel.svelte';
	import PanelHeader from './PanelHeader.svelte';

	let { user, onClose }: { user: Me; onClose: () => void } = $props();

	const uid = $props.id();
</script>

<DismissablePanel {onClose}>
	<section class="account-dialog" aria-labelledby="{uid}-heading" data-testid="account-dialog">
		<PanelHeader title={m.accountDialog_title()} titleId="{uid}-heading" />
		<div class="profile">
			<Avatar name={user.display_name} src={user.avatar_url} size="lg" />
			<div class="profile-text">
				<span class="name">{user.display_name}</span>
				<span class="sub">{m.lobbyMenu_signedIn()}</span>
			</div>
		</div>
		<div class="body">
			<AccountSettings {user} />
		</div>
	</section>
</DismissablePanel>

<style lang="scss">
	@use '$lib/styles/forms';

	// same frame as Settings: capped height, the body scrolls
	.account-dialog {
		@include forms.dialog-panel(30rem, $dismissable: true);
		max-height: min(48rem, calc(100dvh - var(--space-6)));
	}

	.profile {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.profile-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.name {
		overflow: hidden;
		font-size: var(--font-size-lg);
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sub {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.body {
		@include forms.dialog-scroll-body;
		padding: var(--space-1) var(--space-2) var(--space-2);
	}
</style>
