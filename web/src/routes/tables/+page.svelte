<script lang="ts">
	import { goto } from '$app/navigation';
	import { m } from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import CreateTableDialog from '$lib/ui/CreateTableDialog.svelte';
	import { fetchTables, type TableSummary } from '$lib/net/lobby';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import { hasJoinedTable } from '$lib/ui/settings-storage';
	import BackButton from '$lib/ui/BackButton.svelte';
	import RotateCw from '@lucide/svelte/icons/rotate-cw';
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
	// seat is open and switches to the spectator view once none is.
	const REFRESH_MS = 5000;
	let tables = $state<TableSummary[] | null>(null);
	let tablesError = $state(false);
	let refreshing = $state(false);
	// a static stamp of the last successful poll, not a ticking "n seconds ago".
	let updatedAt = $state<Date | null>(null);
	let updatedLabel = $derived(
		updatedAt
			? updatedAt.toLocaleTimeString(getLocale(), { hour: 'numeric', minute: '2-digit' })
			: null
	);

	async function refreshTables(): Promise<void> {
		refreshing = true;
		try {
			const listed = await fetchTables();
			tables = listed.toSorted((a, b) => Number(b.status === 'open') - Number(a.status === 'open'));
			tablesError = false;
			updatedAt = new Date();
		} catch {
			tablesError = true;
		} finally {
			refreshing = false;
		}
	}

	let showCreateDialog = $state(false);

	$effect(() => {
		refreshTables();
		const timer = setInterval(refreshTables, REFRESH_MS);
		return () => clearInterval(timer);
	});
</script>

<div class="tables-page">
	<header class="page-header">
		<BackButton label={m.tablesPage_backLabel()} href="/" />
		<h1>{m.tablesPage_title()}</h1>
		<div class="refresh">
			{#if updatedLabel}
				<span class="updated" data-testid="tables-updated"
					>{m.tablesPage_updatedAt({ time: updatedLabel })}</span
				>
			{/if}
			<button
				type="button"
				class="refresh-btn"
				data-testid="tables-refresh"
				disabled={refreshing}
				onclick={refreshTables}
			>
				<RotateCw size="1.1em" />
				{m.tablesPage_refreshButton()}
			</button>
		</div>
	</header>

	<JoinByCodePanel bind:code={joinCode} codeValid={joinCodeValid} onSubmit={joinTable} />

	{#if tablesError && tables === null}
		<p class="hint">{m.tablesPage_errorHint()}</p>
	{:else if tables === null}
		<p class="hint">{m.tablesPage_loadingHint()}</p>
	{:else if tables.length === 0}
		<div class="empty" data-testid="tables-empty">
			<p class="empty-title">{m.tablesPage_emptyTitle()}</p>
			<p class="hint">{m.tablesPage_emptyHint()}</p>
			<button
				type="button"
				class="primary"
				data-testid="tables-create-table"
				onclick={() => (showCreateDialog = true)}>{m.lobby_createTableButton()}</button
			>
		</div>
	{:else}
		<ul class="table-grid" aria-label={m.tablesPage_tablesAriaLabel()}>
			{#each tables as table (table.id)}
				<TableCard
					{table}
					hasJoined={hasJoinedTable(table.id)}
					onOpen={(id) => goto(`/table/${id}`)}
				/>
			{/each}
		</ul>
	{/if}
</div>

{#if showCreateDialog}
	<CreateTableDialog
		onCreated={(id) => {
			showCreateDialog = false;
			goto(`/table/${id}`);
		}}
		onCancel={() => (showCreateDialog = false)}
	/>
{/if}

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
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3) var(--space-4);

		h1 {
			margin: 0;
			margin-inline-end: auto;
			font-size: var(--font-size-xl);
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
		grid-template-columns: repeat(auto-fill, minmax(19rem, 1fr));
		gap: var(--space-5);
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

	.refresh {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.updated {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.refresh-btn {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
	}

	.empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-8) var(--space-5);
		border: 1px dashed var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface) 85%, transparent);
		text-align: center;
	}

	.empty-title {
		margin: 0;
		font-size: var(--font-size-lg);
		font-weight: 700;
	}
</style>
