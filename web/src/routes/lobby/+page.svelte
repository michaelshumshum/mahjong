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
</script>

<h1>Lobby</h1>
<p class="tagline">
	Play with people you already know. Create a room and share the code, or join one.
</p>

<div class="panels">
	<section class="panel">
		<h2>Create a room</h2>
		<p class="hint">Generates an invite code to share with your table.</p>

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
		<p class="hint">Enter an invite code someone shared with you.</p>

		<form onsubmit={joinRoom}>
			<label for="join-code">Invite code</label>
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
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.tagline {
		color: var(--color-text-muted);
		max-width: 48ch;
	}

	.panels {
		display: grid;
		gap: var(--space-5);
		margin-top: var(--space-5);

		@include layout.tablet-up {
			grid-template-columns: 1fr 1fr;
			align-items: start;
		}
	}

	.panel {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
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
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		padding: var(--space-2) var(--space-3);
		width: 100%;
		max-width: 12ch;
	}

	input:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	button {
		font: inherit;
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: var(--color-surface-raised);
		color: var(--color-text);
		padding: var(--space-2) var(--space-4);
		cursor: pointer;
	}

	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	button.primary {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-text);
		font-weight: 600;
	}
</style>
