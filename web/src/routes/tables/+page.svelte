<script lang="ts">
	import { goto } from '$app/navigation';
	import { fetchTables, type TableSummary } from '$lib/net/lobby';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import JoinByCodePanel from './_components/JoinByCodePanel.svelte';
	import TableCard from './_components/TableCard.svelte';

	claimMuralVisible();

	let joinCode = $state('');
	const joinCodeValid = $derived(joinCode.trim().length > 0);

	function joinTable(): void {
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

	<JoinByCodePanel bind:code={joinCode} codeValid={joinCodeValid} onSubmit={joinTable} />

	{#if tablesError && tables === null}
		<p class="hint">Couldn't reach the server.</p>
	{:else if tables === null}
		<p class="hint">Loading…</p>
	{:else if tables.length === 0}
		<p class="hint">No tables right now — create one from the lobby and invite others.</p>
	{:else}
		<ul class="table-grid" aria-label="Tables">
			{#each tables as table (table.id)}
				<TableCard {table} onOpen={(id) => goto(`/table/${id}`)} />
			{/each}
		</ul>
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.tables-page {
		position: relative;
		z-index: var(--z-hud);
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

	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.table-grid {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(16rem, 1fr));
		gap: var(--space-4);
	}

	button {
		font: inherit;
		padding: var(--space-2) var(--space-4);
		min-height: 44px;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	button.ghost {
		@include buttons.btn-ghost;
	}
</style>
