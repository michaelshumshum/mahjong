<script lang="ts">
	import { getLocale, setLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import { accountSession } from '$lib/net/account-session.svelte';
	import AccountPanel from './AccountPanel.svelte';
	import Avatar from './Avatar.svelte';
	import BookOpen from '@lucide/svelte/icons/book-open';
	import Languages from '@lucide/svelte/icons/languages';
	import LogOut from '@lucide/svelte/icons/log-out';
	import MenuIcon from '@lucide/svelte/icons/menu';
	import ScrollText from '@lucide/svelte/icons/scroll-text';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import UserRound from '@lucide/svelte/icons/user-round';
	import UserRoundPen from '@lucide/svelte/icons/user-round-pen';

	let {
		guestName = null,
		onOpenGuide,
		onOpenSettings,
		onEditGuestName,
		onOpenAccount,
		onOpenGames
	}: {
		guestName?: string | null;
		onOpenGuide: () => void;
		onOpenSettings: () => void;
		onEditGuestName: () => void;
		onOpenAccount: () => void;
		onOpenGames: () => void;
	} = $props();

	const uid = $props.id();
	const ICON = { size: 18, strokeWidth: 1.8, 'aria-hidden': true } as const;
	const otherLocale = getLocale() === 'en' ? 'zh-Hant' : 'en';

	let open = $state(false);
	let root = $state<HTMLElement>();
	let trigger = $state<HTMLButtonElement>();
	let signingOut = $state(false);
	let signOutError = $state<string | null>(null);

	const status = $derived(accountSession.state.status);
	const user = $derived(accountSession.user);

	function close(refocus = false): void {
		open = false;
		signOutError = null;
		if (refocus) trigger?.focus();
	}

	// refocus the trigger first so the dialog hands focus back to it on close
	function openDialog(show: () => void): void {
		close(true);
		show();
	}

	$effect(() => {
		if (!open) return;
		function onPointerDown(event: PointerEvent): void {
			if (!root?.contains(event.target as Node)) close();
		}
		function onKeydown(event: KeyboardEvent): void {
			if (event.key !== 'Escape') return;
			event.preventDefault();
			close(true);
		}
		document.addEventListener('pointerdown', onPointerDown);
		document.addEventListener('keydown', onKeydown);
		return () => {
			document.removeEventListener('pointerdown', onPointerDown);
			document.removeEventListener('keydown', onKeydown);
		};
	});

	// a null relatedTarget is a click on non-focusable panel text, not focus leaving
	function handleFocusOut(event: FocusEvent): void {
		const next = event.relatedTarget as Node | null;
		if (open && next && !root?.contains(next)) close();
	}

	async function handleSignOut(): Promise<void> {
		signingOut = true;
		signOutError = null;
		try {
			await accountSession.signOut();
		} catch {
			signOutError = m.accountPanel_signOutError();
		} finally {
			signingOut = false;
		}
	}
</script>

<div class="lobby-menu" bind:this={root} onfocusout={handleFocusOut}>
	<button
		bind:this={trigger}
		type="button"
		class="trigger"
		data-testid="lobby-menu-button"
		aria-label={m.lobbyMenu_button()}
		aria-expanded={open}
		aria-controls="{uid}-panel"
		onclick={() => (open ? close() : (open = true))}
	>
		{#if user}
			<Avatar name={user.display_name} src={user.avatar_url} />
		{/if}
		<MenuIcon {...ICON} />
	</button>

	{#if open}
		<div class="panel" id="{uid}-panel" data-testid="lobby-menu">
			{#if user}
				<div class="profile">
					<Avatar name={user.display_name} src={user.avatar_url} size="lg" />
					<div class="profile-text">
						<span class="name" data-testid="lobby-menu-name">{user.display_name}</span>
						<span class="sub">{m.lobbyMenu_signedIn()}</span>
					</div>
				</div>
				<button
					type="button"
					class="item"
					data-testid="lobby-menu-account"
					aria-haspopup="dialog"
					onclick={() => openDialog(onOpenAccount)}
				>
					<UserRound {...ICON} />
					<span class="item-label">{m.lobbyMenu_account()}</span>
				</button>
				<button
					type="button"
					class="item"
					data-testid="lobby-menu-games"
					aria-haspopup="dialog"
					onclick={() => openDialog(onOpenGames)}
				>
					<ScrollText {...ICON} />
					<span class="item-label">{m.myGames_heading()}</span>
				</button>
				<hr class="divider" />
			{:else if status === 'guest'}
				<div class="guest">
					<AccountPanel />
				</div>
				<hr class="divider" />
			{/if}

			{#if !user}
				<button
					type="button"
					class="item"
					data-testid="lobby-menu-guest-name"
					aria-haspopup="dialog"
					onclick={() => openDialog(onEditGuestName)}
				>
					<UserRoundPen {...ICON} />
					<span class="item-label">{m.lobbyMenu_guestName()}</span>
					{#if guestName}
						<span class="item-value">{guestName}</span>
					{/if}
				</button>
			{/if}

			<button
				type="button"
				class="item"
				data-testid="lobby-guide"
				aria-haspopup="dialog"
				onclick={() => openDialog(onOpenGuide)}
			>
				<BookOpen {...ICON} />
				<span class="item-label">{m.lobby_guideButton()}</span>
			</button>
			<button
				type="button"
				class="item"
				data-testid="lobby-settings"
				aria-haspopup="dialog"
				onclick={() => openDialog(onOpenSettings)}
			>
				<SettingsIcon {...ICON} />
				<span class="item-label">{m.settings_title()}</span>
			</button>
			<button
				type="button"
				class="item"
				data-testid="lobby-language"
				onclick={() => setLocale(otherLocale)}
			>
				<Languages {...ICON} />
				<span class="item-label" lang={otherLocale}>{m.lobby_languageButton()}</span>
			</button>

			{#if user}
				<hr class="divider" />
				<button
					type="button"
					class="item item--quiet"
					data-testid="lobby-menu-sign-out"
					disabled={signingOut}
					onclick={handleSignOut}
				>
					<LogOut {...ICON} />
					<span class="item-label">{m.accountPanel_signOut()}</span>
				</button>
				{#if signOutError}
					<p class="error" role="alert">{signOutError}</p>
				{/if}
			{/if}
		</div>
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';

	.lobby-menu {
		position: relative;
	}

	.trigger {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-width: var(--tap-target-min);
		justify-content: center;

		:global(svg) {
			flex-shrink: 0;
			color: var(--color-brass);
		}

		&[aria-expanded='true'] {
			border-color: color-mix(in srgb, var(--color-brass) 55%, var(--color-border) 45%);
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}

	.panel {
		position: absolute;
		top: calc(100% + var(--space-2));
		right: 0;
		z-index: var(--z-overlay);
		display: flex;
		flex-direction: column;
		width: min(20rem, calc(100vw - 2 * var(--space-4)));
		max-height: calc(100dvh - var(--tap-target-min) - var(--space-8));
		overflow-y: auto;
		padding: var(--space-2);
		background: var(--color-surface);
		@include buttons.panel-elevated;

		@include a11y.motion-ok {
			animation: menu-in var(--dur-2) var(--ease-out);
		}
	}

	@keyframes menu-in {
		from {
			opacity: 0;
			translate: 0 calc(-1 * var(--space-2));
		}
	}

	.profile {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-2) var(--space-3) var(--space-3);
	}

	.profile-text {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.name {
		overflow: hidden;
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sub {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.guest {
		padding: var(--space-2) var(--space-3) var(--space-3);
	}

	.item {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		min-height: var(--tap-target-min);
		padding: 0 var(--space-3);
		border: none;
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text);
		font: inherit;
		font-weight: 600;
		text-align: start;
		text-decoration: none;
		cursor: pointer;
		transition: background-color var(--dur-control) ease;

		:global(svg) {
			flex-shrink: 0;
			color: var(--color-brass);
		}

		&:hover:not(:disabled) {
			background: rgb(255 255 255 / 0.06);
		}

		&:disabled {
			opacity: 0.5;
			cursor: not-allowed;
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}

	.item-label {
		flex: 1;
	}

	.item-value {
		max-width: 50%;
		overflow: hidden;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 400;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.item--quiet {
		color: var(--color-text-muted);

		:global(svg) {
			color: inherit;
		}
	}

	.divider {
		margin: var(--space-2) 0;
		border: none;
		border-top: 1px solid var(--color-border);
	}

	.error {
		margin: var(--space-1) var(--space-3) var(--space-2);
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}
</style>
