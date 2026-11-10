<script lang="ts">
	import { untrack } from 'svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { accountSession } from '$lib/net/account-session.svelte';
	import { MAX_NAME_LENGTH } from '$lib/net/protocol.constants';
	import AccountPanel from './AccountPanel.svelte';
	import ModalDialog from './ModalDialog.svelte';
	import PanelHeader from './PanelHeader.svelte';

	let {
		initialName = '',
		editing = false,
		onSave,
		onClose
	}: {
		initialName?: string;
		// opened from the menu to rename, not the first-visit prompt
		editing?: boolean;
		onSave: (name: string) => void;
		onClose: () => void;
	} = $props();

	const uid = $props.id();
	// a draft seeded once on open
	let name = $state(untrack(() => initialName));
	const trimmed = $derived(name.trim());

	function submit(event: SubmitEvent): void {
		event.preventDefault();
		if (trimmed) onSave(trimmed);
	}
</script>

<ModalDialog labelledby="{uid}-heading" onCancel={onClose}>
	<div class="welcome-dialog" data-testid="welcome-dialog">
		<PanelHeader
			title={editing ? m.welcomeDialog_editTitle() : m.welcomeDialog_title()}
			titleId="{uid}-heading"
		/>

		{#if accountSession.state.status === 'guest'}
			<AccountPanel />
			<p class="or" aria-hidden="true"><span>{m.welcomeDialog_or()}</span></p>
		{/if}

		<form class="guest-form" onsubmit={submit}>
			<label class="name">
				<span>{m.welcomeDialog_nameLabel()}</span>
				<input
					bind:value={name}
					required
					maxlength={MAX_NAME_LENGTH}
					autocomplete="nickname"
					data-autofocus
					data-testid="welcome-name"
				/>
				<span class="hint">{m.welcomeDialog_nameHint()}</span>
			</label>
			<div class="actions">
				<button type="button" class="secondary" data-testid="welcome-later" onclick={onClose}>
					{editing ? m.welcomeDialog_cancelButton() : m.welcomeDialog_laterButton()}
				</button>
				<button type="submit" class="primary" disabled={!trimmed} data-testid="welcome-guest">
					{editing ? m.welcomeDialog_saveButton() : m.welcomeDialog_guestButton()}
				</button>
			</div>
		</form>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';

	.welcome-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(90vw, 26rem);
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	p {
		margin: 0;
	}

	// a rule either side of the word
	.or {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);

		&::before,
		&::after {
			content: '';
			flex: 1;
			border-top: 1px solid var(--color-border);
		}
	}

	.guest-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.name {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		font-weight: 600;

		input {
			@include buttons.input-recessed;
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-3);
			color: var(--color-text);
			font: inherit;
			font-weight: 400;
		}
	}

	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 400;
		line-height: 1.35;
	}

	.actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-3);
	}

	.primary {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
	}

	.secondary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}

	.primary,
	.secondary {
		&:focus-visible {
			@include a11y.focus-ring;
		}
	}
</style>
