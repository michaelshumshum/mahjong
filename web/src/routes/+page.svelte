<script lang="ts">
	import { onDestroy } from 'svelte';
	import { MahjongSocket } from '$lib/net/socket';
	import { reduce } from '$lib/net/reducer';
	import type { Pong } from '$lib/net/protocol';
	import TileFace from '$lib/table/TileFace.svelte';
	import type { TileCode } from '$lib/table/tile-code';
	import ClaimButtons, { type ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import FaanBreakdown, { type FaanPattern, type Payments } from '$lib/ui/FaanBreakdown.svelte';
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';

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

	// FaanBreakdown demo (this sub-task): mock hand_end data, no real scoring exists yet
	// (docs/05-roadmap.md §2 M2). Patterns sourced from docs/01-rules-spec.md §7.
	//
	// Plain hand: discard win, 5 faan, half_spicy P(5) = 24 (docs/01-rules-spec.md §8).
	const plainPatterns: FaanPattern[] = [
		{ name: 'All Sequences', faan: 1 },
		{ name: 'No Flowers', faan: 1 },
		{ name: 'Fully Concealed', faan: 1 },
		{ name: 'Half Flush', faan: 3 }
	];
	const plainPayments: Payments = { 0: -24, 2: 24 };

	// Capped hand: Full Flush (6) + All Pungs (3) + Self-Draw (1) + No Flowers (1) = 11,
	// clamped to the default faan_cap of 10 (docs/01-rules-spec.md §7's own Full
	// Flush+All Pungs stacking example, extended past the cap). Self-draw, half_spicy
	// P(10) = 128: winner +1.5P, each of the other three -0.5P.
	const cappedPatterns: FaanPattern[] = [
		{ name: 'Full Flush', faan: 6 },
		{ name: 'All Pungs', faan: 3 },
		{ name: 'Self-Draw', faan: 1 },
		{ name: 'No Flowers', faan: 1 }
	];
	const cappedPayments: Payments = { 0: -64, 1: -64, 2: 192, 3: -64 };

	// ScoreSheet demo (this sub-task): mock score/game_end data — like hand_end above, still
	// doc-only sketches with no server model yet (docs/02-protocol.md §3). EAST_ONLY (一圈,
	// docs/05-roadmap.md §5 resolved decision #3) means a full game is one round: dealer stays on
	// a win/draw, otherwise passes counter-clockwise, so a 4-hand game here is the *minimum*
	// length, not a fixed count. Deltas below are hand-checked to sum to zero per hand and to
	// accumulate exactly to `scoreTotals`.
	const scoreSeats: SeatInfo[] = [
		{ seat: 0, name: 'Alice' },
		{ seat: 1, name: 'Bob' },
		{ seat: 2, name: 'Carol' },
		{ seat: 3, name: 'Dave' }
	];
	const scoreHands: HandRecord[] = [
		{ handNo: 1, dealer: 0, prevailing: 'E', deltas: { 0: -24, 2: 24 } },
		{ handNo: 2, dealer: 1, prevailing: 'E', deltas: { 0: -16, 1: 48, 2: -16, 3: -16 } },
		{ handNo: 3, dealer: 2, prevailing: 'E', deltas: { 0: 10, 1: 10, 2: -30, 3: 10 } },
		{ handNo: 4, dealer: 3, prevailing: 'E', deltas: { 1: -8, 2: -8, 3: 16 } }
	];
	// running total after hand 4: {0:-30, 1:50, 2:-30, 3:10}
	const scoreTotals: Totals = { 0: -30, 1: 50, 2: -30, 3: 10 };
	const scoreStandings: Standing[] = [
		{ seat: 1, total: 50 },
		{ seat: 3, total: 10 },
		{ seat: 0, total: -30 },
		{ seat: 2, total: -30 }
	];
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

<section>
	<h2>FaanBreakdown demo</h2>
	<p class="hint">
		Mock <code>hand_end</code> data (docs/02-protocol.md §3) — no real scoring exists yet. First
		card: a plain 5-faan discard win. Second: four patterns stacking to 11 faan, clamped to the
		default <code>faan_cap</code> of 10.
	</p>
	<div class="breakdown-row">
		<FaanBreakdown
			winner={2}
			winningHand={[
				'1s',
				'2s',
				'3s',
				'4s',
				'5s',
				'6s',
				'7s',
				'8s',
				'9s',
				'2s',
				'3s',
				'4s',
				'z5',
				'z5'
			]}
			patterns={plainPatterns}
			totalFaan={5}
			payments={plainPayments}
		/>
		<FaanBreakdown
			winner={2}
			winningHand={[
				'1s',
				'1s',
				'1s',
				'3s',
				'3s',
				'3s',
				'5s',
				'5s',
				'5s',
				'7s',
				'7s',
				'7s',
				'9s',
				'9s'
			]}
			patterns={cappedPatterns}
			totalFaan={10}
			payments={cappedPayments}
		/>
	</div>
</section>

<section>
	<h2>ScoreSheet demo</h2>
	<p class="hint">
		Mock <code>score</code>/<code>game_end</code> data (docs/02-protocol.md §3) — like the
		FaanBreakdown demo above, no real server model exists for these events yet. Four hands of a
		one-round (<code>EAST_ONLY</code>, 一圈) game; deltas per hand sum to zero and accumulate to the
		footer totals and final standings shown below.
	</p>
	<ScoreSheet
		seats={scoreSeats}
		totals={scoreTotals}
		hands={scoreHands}
		standings={scoreStandings}
	/>
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

	.breakdown-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
	}
</style>
