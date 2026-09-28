<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { seatedCount, type TableSummary } from '$lib/net/lobby';

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
	<ul class="seats" aria-label={m.tableCard_seatsAriaLabel()}>
		{#each table.seats as seat, i (i)}
			<li class:seat--open={seat.status === 'empty'}>
				{seat.status === 'empty'
					? m.tableCard_openSeatLabel()
					: (seat.name ?? m.tableCard_guestName())}
				{#if seat.status === 'bot'}<span class="bot-badge">{m.tableCard_botBadge()}</span>{/if}
			</li>
		{/each}
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

	.panel {
		background: var(--color-surface);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		@include buttons.panel-elevated;
	}

	.table-card {
		padding: var(--space-4);
	}

	.card-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.table-code {
		font-family: monospace;
		font-size: var(--font-size-lg);
		letter-spacing: 0.15em;
	}

	.table-state {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		white-space: nowrap;
	}

	.table-state--open {
		color: var(--color-text);
		font-weight: 600;
	}

	.seats {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--space-1) var(--space-3);
		font-size: var(--font-size-sm);

		li {
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}
	}

	.seat--open {
		color: var(--color-text-muted);
		font-style: italic;
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
		font: inherit;
		padding: var(--space-2) var(--space-4);
		min-height: var(--tap-target-min);
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	button.primary {
		@include buttons.btn-primary;
	}
</style>
