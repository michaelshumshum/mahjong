<script lang="ts">
	import type { ConnectionStatus } from '$lib/game/state';
	import type { Seat } from '$lib/table/mock-game-state';
	import { seatWind, WIND_LABEL } from '$lib/table/wind';
	import SeatPicker from '$lib/table/SeatPicker.svelte';
	import SeatRing from '$lib/table/SeatRing.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';

	let {
		tableId,
		onLeaveClick,
		copiedInviteLink,
		copyInviteLinkFailed,
		onCopyInviteLink,
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
		onCopyInviteLink: () => void;
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

	const PRESET_LABELS: Record<string, string> = {
		hk_classic: 'HK Classic',
		hk_casual: 'Casual',
		hk_strict: 'Strict'
	};

	// `rulesetPreset === null` means "custom ruleset" or "no state_sync yet" -- only the spectator
	// snapshot every pre-game connection gets disambiguates them, so this renders only past "Connecting…" below.
	let rulesetKnown = $derived(
		!!effectiveConnection && effectiveConnection !== 'idle' && effectiveConnection !== 'connecting'
	);
</script>

<!-- All three pre-game states share one panel (table code + copy-invite-link) and the seat
	ring's arrangement, matching the real table grid's relative layout. -->
<div class="pretable-panel">
	<BackButton label="Leave game" onclick={onLeaveClick} />
	<div class="pretable-info">
		<span>Table</span>
		<span class="pretable-code">{tableId}</span>
		<button type="button" class="pretable-link-btn" onclick={onCopyInviteLink}>
			{copiedInviteLink ? 'Copied' : 'Copy invite link'}
		</button>
		{#if rulesetKnown}
			<span class="pretable-rules">
				Rules: {rulesetPreset ? (PRESET_LABELS[rulesetPreset] ?? rulesetPreset) : 'Custom'}
			</span>
		{/if}
	</div>
	{#if copyInviteLinkFailed}
		<p class="pretable-error">Couldn't copy automatically — copy the address bar instead.</p>
	{/if}

	{#if !effectiveConnection || effectiveConnection === 'idle' || effectiveConnection === 'connecting'}
		<div class="pretable-center">
			<div class="pretable-spinner"></div>
			<p class="pretable-status">Connecting…</p>
		</div>
	{:else if effectiveSeat === null}
		<h2>Take a seat</h2>
		<FormGroup legend="Your name">
			<input
				id="display-name-input"
				type="text"
				class="pretable-name-input"
				maxlength="24"
				placeholder="Guest"
				autocomplete="off"
				value={displayName}
				oninput={(e) => onDisplayNameChange(e.currentTarget.value)}
			/>
		</FormGroup>
		<SeatPicker {seatStatus} {names} {onJoin} />
	{:else}
		<SeatRing you={effectiveSeat} {dealer} {seatStatus} {names} />
		<h2>You're seated as {WIND_LABEL[seatWind(effectiveSeat, dealer)]}</h2>
		<p>
			Waiting for the rest of the table to join. The hand starts automatically once all four seats
			are ready.
		</p>
		{#if isHost}
			<button type="button" class="pretable-cta" onclick={onStartWithBots}>
				Start with bots
			</button>
			<p class="pretable-hint">Fills every open seat with a bot and starts right away.</p>
		{/if}
	{/if}
</div>

<style lang="scss">
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
		background: var(--color-surface-raised);
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

	.pretable-info {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.pretable-code {
		font-family: monospace;
		font-size: var(--font-size-base);
		letter-spacing: 0.08em;
		color: var(--color-text);
		background: var(--color-surface);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
	}

	.pretable-rules {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.pretable-link-btn {
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;
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

	.pretable-cta {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-primary;
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

	@media (prefers-reduced-motion: reduce) {
		.pretable-spinner {
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
