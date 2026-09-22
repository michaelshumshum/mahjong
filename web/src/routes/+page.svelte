<script lang="ts">
	import { goto } from '$app/navigation';
	import { generateTableCode } from '$lib/table/table-code';

	// Straight to the table, no intermediate copy-code step: the table's own pre-game panel
	// already has a "copy invite link" button (docs/03-frontend.md's "Pre-game states"), so
	// showing the code here too would just be the same one decision rendered twice.
	function createTable(): void {
		goto(`/table/${generateTableCode()}`);
	}

	// practice mode (docs/05-roadmap.md M4.5): a solo table with seats 1-3 bot-bound from table
	// creation (`?practice=true` on the WS endpoint -- server/app/ws.py's `ws_endpoint`). No
	// invite code to share, so this generates a table id the same way "Create table" does and
	// goes straight to the table, tagged so `/table/[id]` knows to connect in practice mode.
	// `?practice=1` is this route's own query param, translated into `&practice=true` on the
	// actual WS URL by `/table/[id]` -- the two spellings are unrelated.
	function startPractice(): void {
		goto(`/table/${generateTableCode()}?practice=1`);
	}
</script>

<div class="panels">
	<section class="panel">
		<h2>Create a table</h2>
		<p class="hint">
			Generates a table and takes you straight there — invite others once you're seated.
		</p>
		<button type="button" class="primary" onclick={createTable}>Create table</button>
	</section>

	<section class="panel">
		<h2>Find a table</h2>
		<p class="hint">
			Sit down at an open table, watch a game in progress, or join one by its invite code.
		</p>
		<a class="primary" href="/tables">Browse tables</a>
	</section>

	<section class="panel">
		<h2>Practice</h2>
		<p class="hint">Play solo against three bots. No one else needs a code for this one.</p>
		<button type="button" class="primary" onclick={startPractice}>Play vs bots</button>
	</section>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panels {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		padding: var(--space-5);
	}

	.panel {
		background: var(--color-surface);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: min(26rem, 100%);
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

	.primary {
		font: inherit;
		padding: var(--space-2) var(--space-4);
		min-height: 44px;
		cursor: pointer;
		@include buttons.btn-primary;
	}

	a.primary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		text-decoration: none;
	}
</style>
