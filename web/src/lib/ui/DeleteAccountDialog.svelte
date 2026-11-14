<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { deleteMe } from '$lib/net/account';
	import { accountSession } from '$lib/net/account-session.svelte';
	import ModalDialog from './ModalDialog.svelte';
	import PanelHeader from './PanelHeader.svelte';

	let { name, onCancel }: { name: string; onCancel: () => void } = $props();

	let typed = $state('');
	let deleting = $state(false);
	let error = $state<string | null>(null);
	// adr 0028: immediate, no grace period, so the player types their own name first
	const confirmed = $derived(typed.trim() === name);

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!confirmed) return;
		deleting = true;
		error = null;
		try {
			await deleteMe();
			accountSession.setUser(null);
		} catch {
			error = m.deleteAccountDialog_error();
			deleting = false;
		}
	}
</script>

<ModalDialog
	labelledby="delete-account-heading"
	role="alertdialog"
	onCancel={() => !deleting && onCancel()}
>
	<form class="delete-dialog" data-testid="delete-account-dialog" onsubmit={submit}>
		<PanelHeader title={m.deleteAccountDialog_title()} titleId="delete-account-heading" />
		<p class="body">{m.deleteAccountDialog_body()}</p>
		<label class="confirm">
			<span>{m.deleteAccountDialog_confirmLabel({ name })}</span>
			<input
				bind:value={typed}
				autocomplete="off"
				spellcheck="false"
				data-autofocus
				data-testid="delete-account-confirm"
			/>
		</label>
		{#if error}
			<p class="error" role="alert">{error}</p>
		{/if}
		<div class="actions">
			<button type="button" class="secondary" disabled={deleting} onclick={onCancel}>
				{m.deleteAccountDialog_cancelButton()}
			</button>
			<button
				type="submit"
				class="danger"
				disabled={!confirmed || deleting}
				data-testid="delete-account-submit"
			>
				{deleting ? m.deleteAccountDialog_deletingButton() : m.deleteAccountDialog_deleteButton()}
			</button>
		</div>
	</form>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';

	.delete-dialog {
		@include forms.dialog-panel(26rem);
	}

	.body,
	.error {
		margin: 0;
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.body {
		color: var(--color-text-muted);
	}

	.error {
		color: var(--color-status-error);
	}

	.confirm {
		@include forms.labelled-input;
	}

	.actions {
		@include forms.dialog-actions;
	}

	.secondary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}

	.danger {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-primary;
	}
</style>
