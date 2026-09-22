<script lang="ts">
	import { goto } from '$app/navigation';
	import { fetchTables, seatedCount, type TableSummary } from '$lib/net/lobby';

	// invite codes are entirely client-generated (docs/03-frontend.md's "/table/[id] wiring":
	// `[id]` is a real table id, auto-created against the backend on first WS connect), so
	// there is nothing to validate client-side before navigating.
	const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I — avoids look-alikes
	const CODE_LENGTH = 6;

	function generateMockCode(): string {
		let code = '';
		for (let i = 0; i < CODE_LENGTH; i++) {
			code += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
		}
		return code;
	}

	// Straight to the table, no intermediate copy-code step: the table's own pre-game panel
	// already has a "copy invite link" button (docs/03-frontend.md's "Pre-game states"), so
	// showing the code here too would just be the same one decision rendered twice.
	function createTable(): void {
		goto(`/table/${generateMockCode()}`);
	}

	let joinCode = $state('');
	const joinCodeValid = $derived(joinCode.trim().length > 0);

	function joinTable(event: SubmitEvent): void {
		event.preventDefault();
		if (!joinCodeValid) return;
		goto(`/table/${joinCode.trim().toUpperCase()}`);
	}

	// practice mode (docs/05-roadmap.md M4.5): a solo table with seats 1-3 bot-bound from table
	// creation (`?practice=true` on the WS endpoint -- server/app/ws.py's `ws_endpoint`). No
	// invite code to share, so this generates a table id the same way "Create table" does and
	// goes straight to the table, tagged so `/table/[id]` knows to connect in practice mode.
	// `?practice=1` is this route's own query param, translated into `&practice=true` on the
	// actual WS URL by `/table/[id]` -- the two spellings are unrelated.
	function startPractice(): void {
		goto(`/table/${generateMockCode()}?practice=1`);
	}

	// both actions land on the same `/table/<id>`: it shows the seat picker while a seat is
	// open and switches to the spectator view once none is (docs/03-frontend.md's "Spectating").
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

	function playerNames(table: TableSummary): string {
		return table.seats
			.filter((s) => s.status !== 'empty')
			.map((s) => s.name ?? 'Guest')
			.join(', ');
	}
</script>

<div class="lobby">
	<div class="panels">
		<section class="panel">
			<h2>Create a table</h2>
			<p class="hint">
				Generates a table and takes you straight there — invite others once you're seated.
			</p>
			<button type="button" class="primary" onclick={createTable}>Create table</button>
		</section>

		<section class="panel">
			<h2>Join a table</h2>

			<form onsubmit={joinTable}>
				<input
					id="join-code"
					type="text"
					autocomplete="off"
					spellcheck="false"
					maxlength={CODE_LENGTH}
					placeholder="ABC123"
					bind:value={joinCode}
				/>
				<button type="submit" class="primary" disabled={!joinCodeValid}>Join table</button>
			</form>
			<p class="hint">
				Any code works — the table is created automatically the moment someone connects to it, so
				this is a real invite, not a preview.
			</p>
		</section>

		<section class="panel panel--practice">
			<h2>Practice</h2>
			<p class="hint">Play solo against three bots. No one else needs a code for this one.</p>
			<button type="button" class="primary" onclick={startPractice}>Play vs bots</button>
		</section>
	</div>

	<section class="panel panel--browse" aria-labelledby="browse-heading">
		<header class="browse-header">
			<h2 id="browse-heading">Tables</h2>
			<button type="button" class="ghost" onclick={refreshTables}>Refresh</button>
		</header>

		{#if tablesError && tables === null}
			<p class="hint">Couldn't reach the server.</p>
		{:else if tables === null}
			<p class="hint">Loading…</p>
		{:else if tables.length === 0}
			<p class="hint">No tables right now — create one and invite others.</p>
		{:else}
			<ul class="table-list">
				{#each tables as table (table.id)}
					<li class="table-row" data-testid="table-row">
						<div class="table-row-info">
							<span class="table-code">{table.id}</span>
							<span class="table-state" class:table-state--open={table.status === 'open'}>
								{table.status === 'open'
									? `Open · ${seatedCount(table)}/4 seated`
									: `In progress · hand ${table.hand_no}`}
							</span>
							<span class="table-players">{playerNames(table)}</span>
						</div>
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
	</section>
</div>

<style lang="scss">
	@use '$lib/styles/layout';
	@use '$lib/styles/buttons';

	.tagline {
		color: var(--color-text-muted);
		max-width: 48ch;
	}

	.lobby {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		align-items: center;
		padding: var(--space-5);
		min-height: 100vh;

		@include layout.tablet-up {
			flex-direction: row;
			justify-content: center;
		}
	}

	.panels {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(26rem, 100%);
	}

	// full-width row of its own, below create/join — a third, unrelated way in rather than a
	// third tile competing for the same two-column grid create/join already own. The CTA button
	// still caps at the same width the other panels' buttons read at, so gaining the row's full
	// width doesn't turn it into a banner.
	.panel--practice {
		@include layout.tablet-up {
			grid-column: 1 / -1;
		}

		button.primary {
			align-self: flex-start;
			min-width: 12rem;
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

	.panel--browse {
		align-self: stretch;
		width: min(30rem, 100%);

		@include layout.tablet-up {
			align-self: center;
			max-height: calc(100vh - 2 * var(--space-5));
		}
	}

	.browse-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
	}

	.table-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		overflow-y: auto;
	}

	.table-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
		padding: var(--space-3);
		background: var(--color-surface-raised);
		border-radius: var(--radius-sm);
	}

	.table-row-info {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.table-code {
		font-family: monospace;
		font-size: var(--font-size-lg);
		letter-spacing: 0.15em;
	}

	.table-state {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.table-state--open {
		color: var(--color-text);
		font-weight: 600;
	}

	.table-players {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
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
		flex-direction: column;
		gap: var(--space-2);
		align-items: flex-start;
	}

	label {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	input {
		font-family: monospace;
		font-size: var(--font-size-lg);
		letter-spacing: 0.15em;
		text-transform: uppercase;
		color: var(--color-text);
		padding: var(--space-2) var(--space-3);
		width: 100%;
		max-width: 12ch;
		@include buttons.input-recessed;
	}

	input:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
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
