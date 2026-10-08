<script lang="ts">
	import type { ConnectionStatus } from '$lib/game/state';
	import type { Seat } from '$lib/table/mock-game-state';
	import { seatWind, windWord } from '$lib/table/wind';
	import SeatPicker from '$lib/table/SeatPicker.svelte';
	import SeatRing from '$lib/table/SeatRing.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { RULESET_PRESET_OPTIONS } from '$lib/net/ruleset';
	import { m } from '$lib/paraglide/messages.js';

	let {
		tableId,
		onLeaveClick,
		copiedInviteLink,
		copyInviteLinkFailed,
		onInvite,
		isPractice,
		effectiveConnection,
		effectiveSeat,
		dealer,
		displayName,
		onDisplayNameChange,
		seatStatus,
		names,
		onJoin,
		isHost,
		onStartWithBots,
		rulesetPreset
	}: {
		tableId: string;
		onLeaveClick: () => void;
		copiedInviteLink: boolean;
		copyInviteLinkFailed: boolean;
		onInvite: () => void;
		// bots fill every other seat at creation -- nobody to invite.
		isPractice: boolean;
		effectiveConnection: ConnectionStatus | undefined;
		effectiveSeat: Seat | null;
		dealer: Seat;
		displayName: string;
		onDisplayNameChange: (value: string) => void;
		seatStatus: string[];
		names: (string | null)[];
		onJoin: (seat: Seat) => void;
		isHost: boolean;
		onStartWithBots: () => void;
		// `null` covers both "no state_sync yet" and "a custom ruleset" -- rendered identically
		// since neither has a preset name worth showing.
		rulesetPreset: string | null;
	} = $props();

	// `rulesetPreset === null` means "custom ruleset" or "no state_sync yet" -- only the spectator
	// snapshot every pre-game connection gets disambiguates them, so this renders only past "Connecting…" below.
	let rulesetKnown = $derived(
		!!effectiveConnection && effectiveConnection !== 'idle' && effectiveConnection !== 'connecting'
	);

	// reuses the preset labels already migrated for CreateTableDialog/ruleset.ts rather than a
	// second copy of the same three strings.
	let presetLabel = $derived(
		rulesetPreset
			? (RULESET_PRESET_OPTIONS.find((p) => p.id === rulesetPreset)?.label() ?? rulesetPreset)
			: m.pretableScreen_customRuleset()
	);
</script>

<!-- All three pre-game states share one panel (table code + invite) and the seat
	ring's arrangement, matching the real table grid's relative layout. -->
<div class="pretable-panel">
	<BackButton label={m.pretableScreen_leaveGameButton()} onclick={onLeaveClick} />
	<div class="pretable-invite">
		<span class="pretable-code-label">{m.pretableScreen_tableLabel()}</span>
		<span class="pretable-code" data-testid="pretable-code">{tableId}</span>
		{#if rulesetKnown}
			<span class="pretable-rules">
				{m.pretableScreen_rulesLabel({ preset: presetLabel })}
			</span>
		{/if}
		{#if !isPractice}
			<button
				type="button"
				class="pretable-invite-btn"
				class:pretable-invite-btn--done={copiedInviteLink}
				data-testid="pretable-invite"
				onclick={onInvite}
			>
				{copiedInviteLink ? m.pretableScreen_copiedLabel() : m.pretableScreen_inviteButton()}
			</button>
			<span class="sr-only" aria-live="polite"
				>{copiedInviteLink ? m.pretableScreen_copiedLabel() : ''}</span
			>
		{/if}
	</div>
	{#if copyInviteLinkFailed}
		<p class="pretable-error">{m.pretableScreen_copyLinkError()}</p>
	{/if}

	{#if !effectiveConnection || effectiveConnection === 'idle' || effectiveConnection === 'connecting'}
		<div class="pretable-center">
			<div class="pretable-spinner"></div>
			<p class="pretable-status">{m.pretableScreen_connectingStatus()}</p>
		</div>
	{:else if effectiveSeat === null}
		<h2>{m.pretableScreen_takeASeatTitle()}</h2>
		<FormGroup legend={m.pretableScreen_nameLegend()}>
			<input
				id="display-name-input"
				type="text"
				class="pretable-name-input"
				maxlength="24"
				placeholder={m.pretableScreen_namePlaceholder()}
				autocomplete="off"
				value={displayName}
				oninput={(e) => onDisplayNameChange(e.currentTarget.value)}
			/>
		</FormGroup>
		<SeatPicker {seatStatus} {names} {onJoin} />
	{:else}
		<SeatRing you={effectiveSeat} {dealer} {seatStatus} {names} />
		<h2>
			{m.pretableScreen_seatedAsLabel({ wind: windWord(seatWind(effectiveSeat, dealer)) })}
		</h2>
		<p>
			{m.pretableScreen_waitingMessage()}
		</p>
		{#if isHost}
			<button type="button" class="pretable-cta" onclick={onStartWithBots}>
				{m.pretableScreen_startWithBotsButton()}
			</button>
			<p class="pretable-hint">{m.pretableScreen_startWithBotsHint()}</p>
		{/if}
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.pretable-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		width: min(90vw, 28rem);
		max-width: 90vw;
		padding: var(--space-5);
		// same surface as the /tables cards -- this panel is a page, not a modal.
		background: var(--color-surface);
		text-align: center;
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6);
		}

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}

		p {
			margin: 0;
			max-width: 40ch;
			color: var(--color-text-muted);
		}
	}

	.pretable-invite {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		width: 100%;
		padding-bottom: var(--space-4);
		border-bottom: 1px solid var(--color-border);
	}

	.pretable-code-label {
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.12em;
		text-transform: uppercase;
		color: var(--color-text-muted);
	}

	// big enough to read across a room or off a screenshot.
	.pretable-code {
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius-sm);
		background: var(--color-tile);
		color: var(--color-tile-ink);
		font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
		font-size: var(--font-size-xl);
		font-weight: 700;
		letter-spacing: 0.18em;
		line-height: 1.1;
		box-shadow:
			0 2px 0 var(--color-tile-edge),
			0 5px 0 var(--color-tile-side),
			0 8px 14px -4px rgb(10 4 2 / 0.6);
		user-select: all;
	}

	.pretable-rules {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.pretable-invite-btn {
		width: min(100%, 16rem);
		min-height: var(--tap-target-min);
		margin-top: var(--space-1);
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-primary;
	}

	.pretable-invite-btn--done {
		background: color-mix(in srgb, var(--color-positive) 30%, var(--color-surface-raised));
	}

	.pretable-error {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.pretable-center {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
	}

	.pretable-status {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	// secondary: "Invite friends" is the panel's one primary action.
	.pretable-cta {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.pretable-name-input {
		width: 100%;
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		color: var(--color-text);
		text-align: start;
		@include buttons.input-recessed;

		&::placeholder {
			color: var(--color-text-muted);
		}
	}

	// indeterminate connection spinner -- no durationMs to anchor a TimerRing to (unknown,
	// still trying).
	.pretable-spinner {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 3px solid var(--color-border);
		border-top-color: var(--color-accent);
		animation: pretable-spin 900ms linear infinite;
	}

	@keyframes pretable-spin {
		to {
			transform: rotate(360deg);
		}
	}

	.pretable-spinner {
		@include a11y.motion-reduced {
			animation: none;
			opacity: 0.6;
		}
	}

	.pretable-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	// center the FormGroup legend and body inside the centered pre-table panel.
	:global(.pretable-panel .form-group) {
		width: 100%;
		max-width: 16rem;
		text-align: start;
	}
</style>
