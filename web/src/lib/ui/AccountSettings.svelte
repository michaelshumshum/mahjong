<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { patchMe, type Me, type MePatch } from '$lib/net/account';
	import { accountSession } from '$lib/net/account-session.svelte';
	import { MAX_NAME_LENGTH } from '$lib/net/protocol.constants';
	import DeleteAccountDialog from './DeleteAccountDialog.svelte';
	import LegalLinks from './LegalLinks.svelte';
	import TrainingConsentField from './TrainingConsentField.svelte';

	let { user }: { user: Me } = $props();

	const uid = $props.id();
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
</script>

<div class="account-settings" data-testid="account-settings">
	<form
		class="group"
		onsubmit={(event) => {
			event.preventDefault();
			void save({ display_name: name }, m.accountSettings_nameSaved());
		}}
	>
		<label class="legend" for="{uid}-name">{m.accountSettings_nameLabel()}</label>
		<div class="card name-row">
			<input
				id="{uid}-name"
				bind:value={name}
				required
				maxlength={MAX_NAME_LENGTH}
				autocomplete="nickname"
				data-testid="account-name"
			/>
			<button
				type="submit"
				class="secondary"
				disabled={busy || name.trim() === user.display_name}
				data-testid="account-name-save"
			>
				{m.accountSettings_nameSave()}
			</button>
		</div>
	</form>

	<section class="group" aria-labelledby="{uid}-privacy">
		<h3 class="legend" id="{uid}-privacy">{m.accountSettings_privacyHeading()}</h3>
		<div class="card card--padded">
			<TrainingConsentField
				checked={user.training_consent_at !== null}
				disabled={busy}
				onChange={(checked) =>
					void save(
						{ training_consent: checked },
						checked ? m.accountSettings_consentOn() : m.accountSettings_consentOff()
					)}
			/>
		</div>
	</section>

	<div class="card data">
		<span class="label">{m.accountSettings_deleteLabel()}</span>
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

	{#if status}
		<p class="status" class:status--error={status.error} role="status">{status.text}</p>
	{/if}

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

	.group {
		display: flex;
		flex-direction: column;
		margin: 0;
	}

	.legend {
		@include forms.settings-legend;
	}

	.card {
		@include forms.settings-card;
	}

	.card--padded {
		padding-block: var(--space-3);
	}

	.name-row {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding-block: var(--space-3);

		input {
			@include buttons.input-recessed;
			flex: 1 1 auto;
			min-width: 0;
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-3);
			color: var(--color-text);
			font: inherit;
		}
	}

	.data {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding-block: var(--space-3);
	}

	.label {
		@include forms.field-label;
		flex: 1 1 auto;
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
