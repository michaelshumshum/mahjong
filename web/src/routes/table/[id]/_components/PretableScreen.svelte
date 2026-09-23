<script lang="ts">
	import type { ConnectionStatus } from '$lib/game/state';
	import type { Seat } from '$lib/table/mock-game-state';
	import { seatWind, WIND_LABEL } from '$lib/table/wind';
	import SeatPicker from '$lib/table/SeatPicker.svelte';
	import SeatRing from '$lib/table/SeatRing.svelte';
	import FormGroup from '$lib/ui/FormGroup.svelte';

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
		// this table's ruleset preset (docs/02-protocol.md §3's `state_sync.ruleset_preset`) --
		// `null` covers both "no state_sync yet" and "a custom ruleset", rendered identically here
		// since neither has a preset name worth showing; a mock/pregame-preview render (no real
		// `liveStore`) always passes `null` too, same fallback `seatStatus`/`names` above already
		// use for those modes.
		rulesetPreset: string | null;
	} = $props();

	const PRESET_LABELS: Record<string, string> = {
		hk_classic: 'HK Classic',
		hk_casual: 'Casual',
		hk_strict: 'Strict'
	};

	// `rulesetPreset === null` means either "custom ruleset" or "no state_sync yet" -- only the
	// spectator-shaped snapshot every pre-game connection gets (docs/00-architecture.md §3's
	// "Spectating" note) disambiguates them, so this only renders once we're past the plain
	// "Connecting…" spinner below, by which point that snapshot has already landed.
	let rulesetKnown = $derived(
		!!effectiveConnection && effectiveConnection !== 'idle' && effectiveConnection !== 'connecting'
	);
</script>

<!-- All three pre-game states (connecting, seat-picker, waiting) are real, recurring moments in
	a genuinely multiplayer game, not filler between "real" screens -- so they share one panel
	(table code + copy-invite-link) and the seat ring's across/left/right/self arrangement, the
	same relative layout the real table grid uses (docs/03-frontend.md's "Pre-game states"). -->
<div class="pretable-panel">
	<button type="button" class="pretable-leave" onclick={onLeaveClick}>Leave game</button>
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

	.pretable-leave {
		align-self: flex-start;
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;
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
		min-height: 44px;
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-primary;
	}

	.pretable-name-input {
		width: 100%;
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		color: var(--color-text);
		text-align: start;
		@include buttons.input-recessed;

		&::placeholder {
			color: var(--color-text-muted);
		}
	}

	// indeterminate connection spinner -- no durationMs to anchor a TimerRing to (docs/03
	// -frontend.md §5's countdown mechanics are for a known deadline; this is "unknown, still
	// trying").
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
