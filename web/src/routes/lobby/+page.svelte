<script lang="ts">
	import { goto } from '$app/navigation';

	// invite codes are entirely client-generated mock data (docs/05-roadmap.md §6: v1 lobby is
	// private-room + invite-code, not a public room list). there is no room API yet (M1 is the
	// rules engine, M5 is real multiplayer) — this proves the create/join navigation flow only.
	const CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; // no 0/O/1/I — avoids look-alikes
	const CODE_LENGTH = 6;

	function generateMockCode(): string {
		let code = '';
		for (let i = 0; i < CODE_LENGTH; i++) {
			code += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
		}
		return code;
	}

	let hostedCode = $state<string | null>(null);
	let copied = $state(false);
	let copyFailed = $state(false);

	function createRoom(): void {
		hostedCode = generateMockCode();
		copied = false;
		copyFailed = false;
	}

	async function copyCode(): Promise<void> {
		if (!hostedCode) return;
		try {
			await navigator.clipboard.writeText(hostedCode);
			copied = true;
			copyFailed = false;
		} catch {
			copied = false;
			copyFailed = true;
		}
	}

	function enterHostedRoom(): void {
		if (!hostedCode) return;
		goto(`/table/${hostedCode}`);
	}

	let joinCode = $state('');
	const joinCodeValid = $derived(joinCode.trim().length > 0);

	function joinRoom(event: SubmitEvent): void {
		event.preventDefault();
		if (!joinCodeValid) return;
		goto(`/table/${joinCode.trim().toUpperCase()}`);
	}

	// practice mode (docs/05-roadmap.md M4.5): a solo table with seats 1-3 bot-bound from room
	// creation (`?practice=true` on the WS endpoint -- server/app/ws.py's `ws_endpoint`). No
	// invite code to share, so this skips the create/copy step entirely -- generate a room id the
	// same way "create room" does and go straight to the table, tagged so `/table/[id]` knows to
	// connect in practice mode. `?practice=1` is this route's own query param, translated into
	// `&practice=true` on the actual WS URL by `/table/[id]` -- the two spellings are unrelated.
	function startPractice(): void {
		goto(`/table/${generateMockCode()}?practice=1`);
	}
</script>

<div class="panels">
	<section class="panel">
		<h2>Create a room</h2>

		{#if !hostedCode}
			<button type="button" class="primary" onclick={createRoom}>Create room</button>
		{:else}
			<div class="code-display">
				<span class="code" data-testid="hosted-code">{hostedCode}</span>
				<button type="button" onclick={copyCode}>{copied ? 'Copied' : 'Copy'}</button>
			</div>
			{#if copyFailed}
				<p class="status status-error">
					Couldn't copy automatically — select and copy the code above.
				</p>
			{/if}
			<p class="mock-note">
				Mock code, generated in your browser — there's no room server yet, so nobody else can
				actually join this. It's here to prove the create → share → enter flow ahead of the real
				backend (see docs/05-roadmap.md M5).
			</p>
			<div class="actions">
				<button type="button" class="primary" onclick={enterHostedRoom}>Enter room</button>
				<button type="button" onclick={createRoom}>New code</button>
			</div>
		{/if}
	</section>

	<section class="panel">
		<h2>Join a room</h2>

		<form onsubmit={joinRoom}>
			<input
				id="join-code"
				type="text"
				autocomplete="off"
				spellcheck="false"
				maxlength={CODE_LENGTH}
				placeholder="ABC123"
				bind:value={joinCode}
			/>
			<button type="submit" class="primary" disabled={!joinCodeValid}>Join room</button>
		</form>
		<p class="mock-note">
			Not wired to a real backend yet — this just takes you to the table route with the code you
			entered, it doesn't check the code is real or connect you to other players.
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

	.mock-note {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		border-left: 2px solid var(--color-border);
		padding-left: var(--space-3);
	}

	.status-error {
		color: var(--color-status-error);
	}

	.code-display {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.code {
		font-family: monospace;
		font-size: var(--font-size-xl);
		letter-spacing: 0.15em;
		background: var(--color-surface-raised);
		border-radius: var(--radius-sm);
		padding: var(--space-2) var(--space-3);
	}

	.actions {
		display: flex;
		gap: var(--space-3);
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
