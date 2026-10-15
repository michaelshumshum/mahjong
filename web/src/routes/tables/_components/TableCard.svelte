<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { seatedCount, type TableSummary } from '$lib/net/lobby';
	import CompassFelt from '$lib/table/CompassFelt.svelte';

	let {
		table,
		hasJoined,
		onOpen
	}: { table: TableSummary; hasJoined: boolean; onOpen: (id: string) => void } = $props();
</script>

<li class="panel table-card" data-testid="table-card">
	<header class="card-header">
		<span class="table-code">{table.id}</span>
		<span class="table-state" class:table-state--open={table.status === 'open'}>
			{table.status === 'open'
				? m.tableCard_openStatus({ count: seatedCount(table) })
				: m.tableCard_inProgressStatus({ handNo: table.hand_no })}
		</span>
	</header>
	<!-- seat order around the felt as the table itself lays it out: 0 bottom, then
	counter-clockwise (1 right, 2 top, 3 left). -->
	<ul class="compass" aria-label={m.tableCard_compassAriaLabel()}>
		{#each table.seats as seat, i (i)}
			<li class="compass-seat compass-seat--{i}" class:compass-seat--open={seat.status === 'empty'}>
				<span class="compass-name"
					>{seat.status === 'empty'
						? m.tableCard_openSeatLabel()
						: (seat.name ?? m.tableCard_guestName())}</span
				>
				{#if seat.status === 'bot'}<span class="bot-badge">{m.tableCard_botBadge()}</span>{/if}
			</li>
		{/each}
		<li class="compass-felt-cell"><CompassFelt /></li>
	</ul>
	{#if hasJoined}
		<button
			type="button"
			class="primary"
			data-testid="table-card-action"
			onclick={() => onOpen(table.id)}>{m.tableCard_rejoinButton()}</button
		>
	{:else if table.status === 'open'}
		<button
			type="button"
			class="primary"
			data-testid="table-card-action"
			onclick={() => onOpen(table.id)}>{m.tableCard_sitDownButton()}</button
		>
	{:else}
		<button type="button" data-testid="table-card-action" onclick={() => onOpen(table.id)}
			>{m.tableCard_watchButton()}</button
		>
	{/if}
</li>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.panel {
		background: var(--color-surface);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		@include buttons.panel-elevated;
	}

	.table-card {
		padding: var(--space-5);
		gap: var(--space-4);
	}

	.card-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-2);
	}

	.table-code {
		font-family: ui-monospace, 'SFMono-Regular', Menlo, monospace;
		font-size: var(--font-size-lg);
		font-weight: 700;
		letter-spacing: 0.15em;
	}

	.table-state {
		padding: 1px var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-pill);
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
		font-weight: 600;
		white-space: nowrap;
	}

	.table-state--open {
		border-color: color-mix(in srgb, var(--color-positive) 50%, var(--color-border));
		color: var(--color-positive);
	}

	.compass {
		@include layout.seat-compass-grid(5rem);
		margin: 0;
		padding: 0;
		list-style: none;
		font-size: var(--font-size-sm);
	}

	.compass-felt-cell {
		grid-area: felt;
		margin: 0;
	}

	.compass-seat {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		min-width: 0;
	}

	.compass-seat--0 {
		grid-area: bottom;
	}

	// side seats stack the bot badge under the name: a side column is too narrow for both.
	.compass-seat--1,
	.compass-seat--3 {
		flex-direction: column;
		gap: 2px;
	}

	.compass-seat--1 {
		grid-area: right;
		align-items: flex-start;
	}

	.compass-seat--2 {
		grid-area: top;
	}

	.compass-seat--3 {
		grid-area: left;
		align-items: flex-end;
	}

	.compass-name {
		max-width: 100%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 600;
	}

	.compass-seat--open .compass-name {
		padding: 0 var(--space-2);
		border: 1px dashed var(--color-border);
		border-radius: var(--radius-pill);
		color: var(--color-text-muted);
		font-weight: 400;
	}

	.bot-badge {
		margin-inline-start: var(--space-1);
		padding: 0 var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text-muted);
		font-size: 0.75em;
		text-transform: uppercase;
	}

	button {
		@include buttons.btn-base(var(--space-4));
		@include buttons.btn-secondary;
	}

	button.primary {
		@include buttons.btn-primary;
	}
</style>
