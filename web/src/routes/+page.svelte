<script lang="ts">
	import { goto } from '$app/navigation';

	// invite codes are entirely client-generated (docs/03-frontend.md's "/table/[id] wiring":
	// `[id]` is a real table id, auto-created against the backend on first WS connect -- no
	// table-listing API needed), so there is nothing to validate client-side before navigating.
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
			Any code works — the table is created automatically the moment someone connects to it, so this
			is a real invite, not a preview.
		</p>
	</section>

	<section class="panel panel--practice">
		<h2>Practice</h2>
		<p class="hint">Play solo against three bots. No one else needs a code for this one.</p>
		<button type="button" class="primary" onclick={startPractice}>Play vs bots</button>
	</section>
</div>

<style lang="scss">
	@use '$lib/styles/layout';
	@use '$lib/styles/buttons';

	.tagline {
		color: var(--color-text-muted);
		max-width: 48ch;
	}

	.panels {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		align-items: center;
		justify-content: center;
		width: 100%;
		height: 100vh;
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
		width: 33%;
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
</style>
