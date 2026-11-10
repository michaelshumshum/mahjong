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
			<Avatar name={user.display_name} size="lg" />
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
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	// same frame as Settings: capped height, the body scrolls
	.account-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(90vw, 30rem);
		max-height: min(48rem, calc(100dvh - var(--space-6)));
		padding: var(--space-5) var(--space-5) var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6) var(--space-6) var(--space-5);
		}
	}

	// leaves room for DismissablePanel's absolutely positioned close button.
	.account-dialog > :global(.panel-header) {
		padding-inline-end: var(--space-6);
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
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin-inline: calc(-1 * var(--space-2));
		padding: var(--space-1) var(--space-2) var(--space-2);
	}
</style>
