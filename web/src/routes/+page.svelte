<script lang="ts">
	import { goto } from '$app/navigation';
	import { generateTableCode } from '$lib/table/table-code';
	import TileMuralBackground from '$lib/ui/TileMuralBackground.svelte';

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

<TileMuralBackground />

<div class="lobby">
	<h1 class="sr-only">Mahjong</h1>
	<div class="actions">
		<button type="button" class="primary" onclick={createTable}>Create a table</button>
		<button type="button" class="secondary" onclick={startPractice}>Practice vs Bots</button>
	</div>
</div>

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
		min-height: 44px;
		cursor: pointer;
	}

	.primary {
		@include buttons.btn-primary;
	}

	.secondary {
		@include buttons.btn-secondary;
	}
</style>
