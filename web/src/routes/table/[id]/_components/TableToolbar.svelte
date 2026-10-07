<script lang="ts">
	import { seatWind, windWord, WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import type { ConnectionStatus } from '$lib/game/state';
	import type { Seat } from '$lib/table/mock-game-state';

	let {
		spectating,
		tableId,
		isPractice,
		seat,
		dealer,
		wallCount,
		prevailing,
		connection,
		onLeaveClick,
		onToggleScoreSheet,
		onToggleSettings,
		onOpenGuide
	}: {
		spectating: boolean;
		tableId: string;
		isPractice: boolean;
		seat: number | null;
		dealer: Seat;
		wallCount: number;
		prevailing: WindLetter;
		connection?: ConnectionStatus;
		onLeaveClick: () => void;
		onToggleScoreSheet: () => void;
		onToggleSettings: () => void;
		onOpenGuide: () => void;
	} = $props();

	// your own wind, not "seat N" -- CenterHub (frontend.md §3) now owns the table-wide wall/
	// prevailing readout, so this toolbar keeps only what's specific to you.
	let yourWind = $derived(seat !== null ? seatWind(seat as Seat, dealer) : null);
</script>

<header class="table-toolbar">
	<BackButton label={m.tableToolbar_leaveGameLabel()} onclick={onLeaveClick} />
	{#if spectating}
		<p class="table-label">
			{m.tableToolbar_tableLabel()} <strong>{tableId}</strong> · {m.tableToolbar_spectatingLabel()}
		</p>
	{:else}
		<p class="table-label">
			{m.tableToolbar_tableLabel()} <strong>{tableId}</strong> ·
			<strong
				class="your-wind"
				aria-label={yourWind
					? m.tableToolbar_yourWindAriaLabel({ wind: windWord(yourWind) })
					: undefined}>{yourWind ? WIND_CHAR[yourWind] : ''}</strong
			>{#if isPractice}
				· {m.tableToolbar_practiceVsBotsLabel()}{/if}
		</p>
	{/if}

	<div class="table-status" aria-label={m.tableToolbar_tableStatusAriaLabel()}>
		{#if connection === 'resyncing' || connection === 'closed' || connection === 'connecting'}
			<span class="connection-pill" data-testid="connection-pill">
				{connection === 'resyncing'
					? m.tableToolbar_connectionResyncingLabel()
					: m.tableToolbar_connectionReconnectingLabel()}
			</span>
		{/if}
		<!-- CenterHub shows wall/prevailing at tablet-up; kept here, compact, for phones only
		     (frontend.md §3) where the hub collapses out of the way of the discard pools. -->
		<span class="phone-only-status">{m.tableToolbar_wallLabel()} <strong>{wallCount}</strong></span>
		<span class="phone-only-status"
			>{m.tableToolbar_prevailingLabel()} <strong>{WIND_CHAR[prevailing]}</strong></span
		>
	</div>

	<div class="chrome-toggles">
		<button type="button" data-testid="open-guide" onclick={onOpenGuide}
			>{m.tableToolbar_guideButton()}</button
		>
		<button type="button" data-testid="toggle-score-sheet" onclick={onToggleScoreSheet}
			>{m.tableToolbar_scoreSheetButton()}</button
		>
		{#if !spectating}
			<button type="button" data-testid="toggle-settings" onclick={onToggleSettings}
				>{m.tableToolbar_settingsButton()}</button
			>
		{/if}
	</div>
</header>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	.connection-pill {
		padding: 0 var(--space-2);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-accent);
		color: var(--color-accent-on-dark);
		font-weight: 700;
		@include a11y.motion-ok {
			animation: connection-pill-pulse 1.4s ease-in-out infinite;
		}
	}

	@keyframes connection-pill-pulse {
		50% {
			opacity: 0.5;
		}
	}

	.table-toolbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-3);
		z-index: var(--z-hud);
	}

	.chrome-toggles {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.chrome-toggles button {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.table-label {
		margin: 0;
		align-self: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	// dealer/turn aren't reproduced here -- .dealer-badge/.seat-region--turn already say that.
	.table-status {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;

		strong {
			color: var(--color-text);
		}
	}

	.your-wind {
		color: var(--color-text);
	}

	// CenterHub (frontend.md §3) is the tablet-up source for wall/prevailing; below that it
	// collapses out of the pools' way, so this compact copy fills in.
	.phone-only-status {
		display: none;

		@include layout.phone-only {
			display: inline;
		}
	}
</style>
