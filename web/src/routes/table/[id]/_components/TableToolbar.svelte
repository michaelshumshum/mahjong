<script lang="ts">
	import { WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';

	let {
		spectating,
		tableId,
		isPractice,
		seat,
		wallCount,
		prevailing,
		onLeaveClick,
		onToggleScoreSheet,
		onToggleSettings
	}: {
		spectating: boolean;
		tableId: string;
		isPractice: boolean;
		seat: number | null;
		wallCount: number;
		prevailing: WindLetter;
		onLeaveClick: () => void;
		onToggleScoreSheet: () => void;
		onToggleSettings: () => void;
	} = $props();
</script>

<header class="table-toolbar">
	<BackButton label={m.tableToolbar_leaveGameLabel()} onclick={onLeaveClick} />
	{#if spectating}
		<p class="table-label">
			{m.tableToolbar_tableLabel()} <strong>{tableId}</strong> · {m.tableToolbar_spectatingLabel()}
		</p>
	{:else}
		<p class="table-label">
			{m.tableToolbar_tableLabel()} <strong>{tableId}</strong> · {m.tableToolbar_seatLabel({
				seat: seat ?? ''
			})}{#if isPractice}
				· {m.tableToolbar_practiceVsBotsLabel()}{/if}
		</p>
	{/if}

	<div class="table-status" aria-label={m.tableToolbar_tableStatusAriaLabel()}>
		<span>{m.tableToolbar_wallLabel()} <strong>{wallCount}</strong></span>
		<span>{m.tableToolbar_prevailingLabel()} <strong>{WIND_CHAR[prevailing]}</strong></span>
	</div>

	<div class="chrome-toggles">
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
</style>
