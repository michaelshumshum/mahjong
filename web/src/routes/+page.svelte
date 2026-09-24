<script lang="ts">
	import { goto } from '$app/navigation';
	import { createTable } from '$lib/net/lobby';
	import CreateTableDialog from '$lib/ui/CreateTableDialog.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';

	claimMuralVisible();

	// "Create a table" opens a dialog to pick the ruleset (docs/00-architecture.md §3 "Ruleset
	// selection") rather than navigating straight there -- table ids are minted server-side now
	// (`POST /tables`, docs/02-protocol.md §10), and the ruleset has to be chosen before that
	// call since `RuleSet` is fixed at table construction with no path to change it after. The
	// table's own pre-game panel still has its own "copy invite link" button
	// (docs/03-frontend.md's "Pre-game states"), so there's still no separate copy-code step here.
	let showCreateDialog = $state(false);

	function handleCreated(tableId: string): void {
		showCreateDialog = false;
		goto(`/table/${tableId}`);
	}

	// practice mode (docs/05-roadmap.md M4.5): a solo table with seats 1-3 bot-bound from table
	// creation. Stays a single click, no dialog -- practice tables don't need a ruleset choice.
	// `?practice=1` is this route's own query param, translated into `&practice=true` on the
	// live WS URL by `/table/[id]` if a page reload needs to reopen the socket -- the two
	// spellings are unrelated. `practice: true` in the `POST /tables` body is what actually binds
	// the bot seats at construction (`server/app/table.py`'s `Table.__init__(practice=...)`).
	let practiceSubmitting = $state(false);
	let practiceError = $state(false);

	async function startPractice(): Promise<void> {
		practiceSubmitting = true;
		practiceError = false;
		try {
			const { table_id } = await createTable({ practice: true });
			goto(`/table/${table_id}?practice=1`);
		} catch {
			practiceError = true;
			practiceSubmitting = false;
		}
	}
</script>

<div class="lobby">
	<h1 class="sr-only">Mahjong</h1>
	<div class="actions">
		<button type="button" class="primary" onclick={() => (showCreateDialog = true)}>
			Create a table
		</button>
		<a class="secondary" href="/tables">Join a game</a>
		<button type="button" class="secondary" onclick={startPractice} disabled={practiceSubmitting}>
			{practiceSubmitting ? 'Starting…' : 'Practice vs Bots'}
		</button>
		{#if practiceError}
			<p class="lobby-error">Couldn't start a practice table — try again.</p>
		{/if}
	</div>
</div>

{#if showCreateDialog}
	<CreateTableDialog onCreated={handleCreated} onCancel={() => (showCreateDialog = false)} />
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.lobby {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: flex-end;
		justify-content: center;
		min-height: 100dvh;
		padding: var(--space-8) var(--space-5);

		@include layout.phone-only {
			align-items: center;
		}
	}

	.actions {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: min(20rem, 100%);
	}

	.primary,
	.secondary {
		font: inherit;
		font-size: var(--font-size-lg);
		padding: var(--space-3) var(--space-4);
		min-height: var(--tap-target-min);
		cursor: pointer;
	}

	.primary {
		@include buttons.btn-primary;
	}

	.secondary {
		@include buttons.btn-secondary;
	}

	.lobby-error {
		margin: 0;
		text-align: center;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	a.secondary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		text-decoration: none;
	}
</style>
