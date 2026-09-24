<script lang="ts">
	import { WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';

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
	<BackButton label="Leave game" onclick={onLeaveClick} />
	{#if spectating}
		<p class="table-label">
			Table <strong>{tableId}</strong> · spectating
		</p>
	{:else}
		<p class="table-label">
			Table <strong>{tableId}</strong> · seat {seat}{#if isPractice}
				· practice vs bots{/if}
		</p>
	{/if}

	<div class="table-status" aria-label="Table status">
		<span>Wall <strong>{wallCount}</strong></span>
		<span>Prevailing <strong>{WIND_CHAR[prevailing]}</strong></span>
	</div>

	<div class="chrome-toggles">
		<button type="button" onclick={onToggleScoreSheet}>Score sheet</button>
		{#if !spectating}
			<button type="button" onclick={onToggleSettings}>Settings</button>
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

	// wall/prevailing: was `.center-info` on the table surface itself -- dealer/turn moved with
	// it but aren't reproduced here, since `.dealer-badge`/`.seat-region--turn`'s outline on each
	// seat already say that.
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
