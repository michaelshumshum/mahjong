<script lang="ts">
	import { onDestroy } from 'svelte';
	import { MahjongSocket } from '$lib/net/socket';
	import { reduce } from '$lib/net/reducer';
	import type { Pong } from '$lib/net/protocol';
	import TileFace from '$lib/table/TileFace.svelte';
	import type { TileCode } from '$lib/table/tile-code';
	import ClaimButtons, { type ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';

	let status = $state<'idle' | 'connecting' | 'connected'>('idle');
	let lastPong = $state<Pong['d'] | null>(null);

	let socket: MahjongSocket | null = null;
	let unsubscribe: (() => void) | null = null;

	// M0 demo (docs/05-roadmap.md §2): connect, hello, ping, render the pong.
	// No game store yet — reduce() is called here only to exercise the reducer
	// skeleton, its return value is unused.
	function connectAndPing(): void {
		if (socket) return;
		status = 'connecting';

		const s = new MahjongSocket();
		socket = s;
		unsubscribe = s.onEvent((event) => {
			reduce(null, event);
			if (event.t === 'pong') lastPong = event.d;
		});
		s.connect();

		// hello fires on open inside socket.ts; poll briefly for OPEN before
		// pinging rather than adding a send queue for this one demo call.
		const trySend = () => {
			if (s.readyState === WebSocket.OPEN) {
				status = 'connected';
				s.ping();
			} else if (s.readyState === WebSocket.CONNECTING) {
				setTimeout(trySend, 50);
			}
		};
		trySend();
	}

	onDestroy(() => {
		unsubscribe?.();
		socket?.disconnect();
	});

	// M4 slice demo (this sub-task): proves TileFace renders vendored art per code plus a
	// back for concealed/unrendered codes. Not the real hand/table layout.
	const demoCodes: (TileCode | null)[] = ['1m', '9m', '5p', '1s', 'z1', 'z5', 'z7', 'f1', null];

	// ClaimButtons/TimerRing demo (this sub-task): mock props only, no claim_offer wiring.
	// Two chow options on the same discarded 6s (4s-5s vs 5s-7s) exercises the
	// multi-chow-option disambiguation described in docs/02-protocol.md §2.
	const demoClaimOptions: ClaimOption[] = [
		{ kind: 'chow', tiles: ['4s', '5s'] },
		{ kind: 'chow', tiles: ['5s', '7s'] },
		{ kind: 'pung' },
		{ kind: 'win' },
		{ kind: 'pass' }
	];
	let lastChoice = $state<ClaimOption | null>(null);
	function chooseDemo(option: ClaimOption): void {
		lastChoice = option;
	}

	const timerDurations = [8000, 3000, 1200];
	let timerDurationMs = $state(timerDurations[0]);
</script>

<h1>Welcome to SvelteKit</h1>
<p>Visit <a href="https://svelte.dev/docs/kit">svelte.dev/docs/kit</a> to read the documentation</p>

<section>
	<h2>WS connect/ping/pong demo</h2>
	<button onclick={connectAndPing} disabled={status !== 'idle'}>Connect + ping</button>
	<p>status: {status}</p>
	{#if lastPong}
		<p data-testid="pong-result">pong: t0={lastPong.t0} t1={lastPong.t1}</p>
	{/if}
</section>

<section>
	<h2>TileFace demo</h2>
	<div class="tile-row">
		{#each demoCodes as code (code)}
			<figure>
				<TileFace {code} />
				<figcaption>{code ?? 'back'}</figcaption>
			</figure>
		{/each}
	</div>
</section>

<section>
	<h2>TimerRing demo</h2>
	<p class="hint">
		Pick a duration; the ring depletes over that many ms and turns red near expiry.
	</p>
	<div class="timer-controls">
		{#each timerDurations as ms (ms)}
			<button type="button" onclick={() => (timerDurationMs = ms)}>{ms}ms</button>
		{/each}
	</div>
	{#key timerDurationMs}
		<TimerRing durationMs={timerDurationMs} />
	{/key}
</section>

<section>
	<h2>ClaimButtons demo</h2>
	<p class="hint">
		Mock claim_offer with two chow options on the same discard (4s-5s vs 5s-7s), plus pung, win,
		pass. Fixed to the bottom-center of the viewport per docs/03-frontend.md §5.
	</p>
	{#if lastChoice}
		<p data-testid="claim-choice">
			chose: {lastChoice.kind}{lastChoice.tiles ? ` ${lastChoice.tiles.join('-')}` : ''}
		</p>
	{/if}
	<ClaimButtons options={demoClaimOptions} onChoose={chooseDemo} />
</section>

<style lang="scss">
	// proves the styles/ partials are usable from a page — not real component styling (M4).
	@use '$lib/styles/layout';

	section {
		border: 1px solid var(--color-border);
		border-radius: 4px;
		padding: var(--space-3);

		@include layout.tablet-up {
			padding: var(--space-5);
		}
	}

	.tile-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	figure {
		margin: 0;
		text-align: center;
	}

	figure :global(.tile-face) {
		height: 88px;
	}

	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.timer-controls {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
	}
</style>
