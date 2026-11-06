<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { EXPORT_FILENAME, exportMe, patchMe, type Me, type MePatch } from '$lib/net/account';
	import { accountSession } from '$lib/net/account-session.svelte';
	import { MAX_NAME_LENGTH } from '$lib/net/protocol.constants';
	import DeleteAccountDialog from './DeleteAccountDialog.svelte';
	import LegalLinks from './LegalLinks.svelte';
	import TrainingConsentField from './TrainingConsentField.svelte';

	let { user }: { user: Me } = $props();

	let name = $derived(user.display_name);
	let busy = $state(false);
	let status = $state<{ text: string; error: boolean } | null>(null);
	let confirmingDelete = $state(false);

	async function save(patch: MePatch, done: string): Promise<void> {
		busy = true;
		status = null;
		try {
			accountSession.setUser(await patchMe(patch));
			status = { text: done, error: false };
		} catch {
			status = { text: m.accountSettings_saveError(), error: true };
		} finally {
			busy = false;
		}
	}

	async function download(): Promise<void> {
		busy = true;
		status = null;
		try {
			const url = URL.createObjectURL(await exportMe());
			const link = Object.assign(document.createElement('a'), {
				href: url,
				download: EXPORT_FILENAME
			});
			link.click();
			URL.revokeObjectURL(url);
		} catch {
			status = { text: m.accountSettings_exportError(), error: true };
		} finally {
			busy = false;
		}
	}
</script>

<div class="account-settings" data-testid="account-settings">
	<form
		class="row"
		onsubmit={(event) => {
			event.preventDefault();
			void save({ display_name: name }, m.accountSettings_nameSaved());
		}}
	>
		<label class="name">
			<span>{m.accountSettings_nameLabel()}</span>
			<input
				bind:value={name}
				required
				maxlength={MAX_NAME_LENGTH}
				autocomplete="nickname"
				data-testid="account-name"
			/>
		</label>
		<button
			type="submit"
			class="secondary"
			disabled={busy || name.trim() === user.display_name}
			data-testid="account-name-save"
		>
			{m.accountSettings_nameSave()}
		</button>
	</form>

	<TrainingConsentField
		checked={user.training_consent_at !== null}
		disabled={busy}
		onChange={(checked) =>
			void save(
				{ training_consent: checked },
				checked ? m.accountSettings_consentOn() : m.accountSettings_consentOff()
			)}
	/>

	{#if status}
		<p class="status" class:status--error={status.error} role="status">{status.text}</p>
	{/if}

	<div class="data">
		<div class="text">
			<span class="label">{m.accountSettings_exportLabel()}</span>
			<span class="desc">{m.accountSettings_exportDesc()}</span>
		</div>
		<button
			type="button"
			class="secondary"
			disabled={busy}
			data-testid="account-export"
			onclick={download}
		>
			{m.accountSettings_exportButton()}
		</button>
	</div>

	<div class="data">
		<div class="text">
			<span class="label">{m.accountSettings_deleteLabel()}</span>
			<span class="desc">{m.accountSettings_deleteDesc()}</span>
		</div>
		<button
			type="button"
			class="secondary delete"
			disabled={busy}
			data-testid="account-delete"
			onclick={() => (confirmingDelete = true)}
		>
			{m.accountSettings_deleteButton()}
		</button>
	</div>

	<LegalLinks />
</div>

{#if confirmingDelete}
	<DeleteAccountDialog name={user.display_name} onCancel={() => (confirmingDelete = false)} />
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';

	.account-settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	.row {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
	}

	.name {
		display: flex;
		flex: 1 1 auto;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
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

	.data {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding-top: var(--space-4);
		border-top: 1px solid var(--color-border);
	}

	.text {
		@include forms.field-text;
		flex: 1 1 auto;
	}

	.label {
		@include forms.field-label;
	}

	.desc {
		@include forms.field-desc;
	}

	.secondary {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
		flex: none;
	}

	.delete {
		color: var(--color-status-error);
	}

	.status {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.status--error {
		color: var(--color-status-error);
	}
</style>
