<script lang="ts">
	import { afterNavigate, replaceState } from '$app/navigation';
	import { page } from '$app/state';
	import { untrack } from 'svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { accountsEnabled, patchMe, readSigninFlag, type SigninFlag } from '$lib/net/account';
	import { accountSession } from '$lib/net/account-session.svelte';
	import { MAX_NAME_LENGTH } from '$lib/net/protocol.constants';
	import ModalDialog from './ModalDialog.svelte';
	import PanelHeader from './PanelHeader.svelte';
	import TrainingConsentField from './TrainingConsentField.svelte';

	let flag = $state<SigninFlag | null>(null);
	let name = $derived(accountSession.user?.display_name ?? '');
	// unchecked until the player opts in (adr 0028 "Training consent")
	let consent = $state(false);
	let saving = $state(false);
	let error = $state<string | null>(null);

	function takeFlag(): void {
		if (!accountsEnabled()) return;
		const read = readSigninFlag(page.url);
		if (!read.flag) return;
		flag = read.flag;
		try {
			replaceState(read.cleaned, page.state);
		} catch {
			// mounted during hydration (no api gate), before the router starts: afterNavigate's
			// initial call retries, the flag still on the url
		}
	}

	// mounting behind ApiConnectGate misses the initial afterNavigate, so read it on mount too
	$effect(() => untrack(takeFlag));
	afterNavigate(takeFlag);

	async function submit(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		saving = true;
		error = null;
		try {
			accountSession.setUser(await patchMe({ display_name: name, training_consent: consent }));
			flag = null;
		} catch {
			error = m.signinReturn_saveError();
		} finally {
			saving = false;
		}
	}
</script>

{#if flag === 'signup' && accountSession.user}
	<ModalDialog labelledby="signup-heading" onCancel={() => !saving && (flag = null)}>
		<form class="signin-dialog" data-testid="signup-dialog" onsubmit={submit}>
			<PanelHeader title={m.signinReturn_signupTitle()} titleId="signup-heading" />
			<p class="hint">{m.signinReturn_signupHint()}</p>
			<label class="name">
				<span>{m.signinReturn_nameLabel()}</span>
				<input
					bind:value={name}
					required
					maxlength={MAX_NAME_LENGTH}
					autocomplete="nickname"
					data-autofocus
					data-testid="signup-name"
				/>
			</label>
			<TrainingConsentField checked={consent} onChange={(checked) => (consent = checked)} />
			{#if error}
				<p class="error" role="alert">{error}</p>
			{/if}
			<div class="actions">
				<button type="submit" class="primary" disabled={saving} data-testid="signup-submit">
					{saving ? m.signinReturn_savingButton() : m.signinReturn_continueButton()}
				</button>
			</div>
		</form>
	</ModalDialog>
{:else if flag === 'failed' || flag === 'disabled'}
	<ModalDialog labelledby="signin-error-heading" role="alertdialog" onCancel={() => (flag = null)}>
		<div class="signin-dialog" data-testid="signin-error-dialog">
			<PanelHeader
				title={flag === 'failed' ? m.signinReturn_failedTitle() : m.signinReturn_disabledTitle()}
				titleId="signin-error-heading"
			/>
			<p class="hint">
				{flag === 'failed' ? m.signinReturn_failedBody() : m.signinReturn_disabledBody()}
			</p>
			<div class="actions">
				<button type="button" class="primary" data-autofocus onclick={() => (flag = null)}>
					{m.signinReturn_okButton()}
				</button>
			</div>
		</div>
	</ModalDialog>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.signin-dialog {
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

	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
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

	.error {
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}

	.actions {
		display: flex;
		justify-content: flex-end;
	}

	.primary {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
	}
</style>
