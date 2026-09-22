<script lang="ts">
	import { goto } from '$app/navigation';
	import { fetchTables, seatedCount, type TableSummary } from '$lib/net/lobby';
	import { TABLE_CODE_LENGTH } from '$lib/table/table-code';

	let joinCode = $state('');
	const joinCodeValid = $derived(joinCode.trim().length > 0);

	function joinTable(event: SubmitEvent): void {
		event.preventDefault();
		if (!joinCodeValid) return;
		goto(`/table/${joinCode.trim().toUpperCase()}`);
	}

	// sit down and watch both land on the same `/table/<id>`: it shows the seat picker while a
	// seat is open and switches to the spectator view once none is (docs/03-frontend.md's
	// "Spectating").
	const REFRESH_MS = 5000;
	let tables = $state<TableSummary[] | null>(null);
	let tablesError = $state(false);

	async function refreshTables(): Promise<void> {
		try {
			const listed = await fetchTables();
			tables = listed.toSorted((a, b) => Number(b.status === 'open') - Number(a.status === 'open'));
			tablesError = false;
		} catch {
			tablesError = true;
		}
	}

	$effect(() => {
		refreshTables();
		const timer = setInterval(refreshTables, REFRESH_MS);
		return () => clearInterval(timer);
	});
</script>

<div class="tables-page">
	<header class="page-header">
		<a class="back-link" href="/">← Lobby</a>
		<h1>Tables</h1>
		<button type="button" class="ghost" onclick={refreshTables}>Refresh</button>
	</header>

	<section class="panel join-panel" aria-labelledby="join-heading">
		<h2 id="join-heading">Join by code</h2>
		<form onsubmit={joinTable}>
			<input
				id="join-code"
				type="text"
				autocomplete="off"
				spellcheck="false"
				maxlength={TABLE_CODE_LENGTH}
				placeholder="ABC123"
				aria-label="Table code"
				bind:value={joinCode}
			/>
			<button type="submit" class="primary" disabled={!joinCodeValid}>Join table</button>
		</form>
		<p class="hint">
			Any code works — the table is created automatically the moment someone connects to it, so this
			is a real invite, not a preview.
		</p>
	</section>

	{#if tablesError && tables === null}
		<p class="hint">Couldn't reach the server.</p>
	{:else if tables === null}
		<p class="hint">Loading…</p>
	{:else if tables.length === 0}
		<p class="hint">No tables right now — create one from the lobby and invite others.</p>
	{:else}
		<ul class="table-grid" aria-label="Tables">
			{#each tables as table (table.id)}
				<li class="panel table-card" data-testid="table-card">
					<header class="card-header">
						<span class="table-code">{table.id}</span>
						<span class="table-state" class:table-state--open={table.status === 'open'}>
							{table.status === 'open'
								? `Open · ${seatedCount(table)}/4`
								: `In progress · hand ${table.hand_no}`}
						</span>
					</header>
					<ul class="seats" aria-label="Seats">
						{#each table.seats as seat, i (i)}
							<li class:seat--open={seat.status === 'empty'}>
								{seat.status === 'empty' ? 'Open seat' : (seat.name ?? 'Guest')}
								{#if seat.status === 'bot'}<span class="bot-badge">Bot</span>{/if}
							</li>
						{/each}
					</ul>
					{#if table.status === 'open'}
						<button type="button" class="primary" onclick={() => goto(`/table/${table.id}`)}
							>Sit down</button
						>
					{:else}
						<button type="button" onclick={() => goto(`/table/${table.id}`)}>Watch</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.tables-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(72rem, 100%);
		margin: 0 auto;
		padding: var(--space-5);
	}

	.page-header {
		display: flex;
		align-items: center;
		gap: var(--space-4);

		h1 {
			margin: 0;
			margin-inline-end: auto;
			font-size: var(--font-size-xl);
		}
	}

	.back-link {
		color: var(--color-text-muted);
		text-decoration: none;

		&:hover {
			color: var(--color-text);
		}
	}

	.panel {
		background: var(--color-surface);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		@include buttons.panel-elevated;
	}

	.panel h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}

	input {
		font-family: monospace;
		font-size: var(--font-size-lg);
		letter-spacing: 0.15em;
		text-transform: uppercase;
		color: var(--color-text);
		padding: var(--space-2) var(--space-3);
		width: 12ch;
		@include buttons.input-recessed;
	}

	input:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	.table-grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: var(--space-4);
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
		min-height: 44px;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	button.primary {
		@include buttons.btn-primary;
	}

	button.ghost {
		@include buttons.btn-ghost;
	}
</style>
