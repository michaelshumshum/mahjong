<script lang="ts">
	import TileFace from '$lib/table/TileFace.svelte';
	import {
		MOCK_SCENARIOS,
		relativeSeat,
		type MockMeld,
		type MockSeatState,
		type Seat
	} from '$lib/table/mock-game-state';
	import ClaimButtons, { type ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';
	import Chat, { type ChatEntry } from '$lib/ui/Chat.svelte';
	import Settings, { type AutoArm, type ClientPrefs } from '$lib/ui/Settings.svelte';
	import Toast from '$lib/ui/Toast.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';
	import {
		initialSlotState,
		popSlotForDiscard,
		popSlotsForConcealedKong,
		pushDrawnSlot,
		type SlotState
	} from '$lib/table/tile-slots';
	import type { TileCode } from '$lib/table/tile-code';

	const WIND_LABEL: Record<string, string> = { E: 'East', S: 'South', W: 'West', N: 'North' };
	const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const;

	// dev-only scenario switch (this sub-task's "genuinely demonstrable, not a frozen
	// screenshot" requirement) — real integration replaces this with the store the reducer
	// fills from the WS stream (docs/03-frontend.md §6), one scenario at a time.
	let scenarioId = $state(MOCK_SCENARIOS[0].id);
	let gameState = $derived(MOCK_SCENARIOS.find((s) => s.id === scenarioId)!.state);

	function seatAt(position: 0 | 1 | 2 | 3): MockSeatState {
		return gameState.seats.find((s) => relativeSeat(s.seat, gameState.you) === position)!;
	}

	// seat wind badge: the dealer holds East for the current hand, remaining seats follow
	// clockwise in seat-index space — a badge only, never position (§10 "What stays").
	function seatWind(seat: Seat): (typeof SEAT_WINDS)[number] {
		return SEAT_WINDS[(seat - gameState.dealer + 4) % 4];
	}

	let claimOptions: ClaimOption[] | null = $derived(
		gameState.claimWindow?.yourOptions
			? gameState.claimWindow.yourOptions.map((o) => ({ kind: o.kind, tiles: o.tiles }))
			: null
	);
	let lastClaimChoice: ClaimOption | null = $state(null);
	function chooseClaim(option: ClaimOption): void {
		lastClaimChoice = option;
	}

	// minimal chrome to prove ScoreSheet/Chat/Settings/Toast compose into the scene without
	// layout collision (this sub-task's scope) — not the final chrome, just reachability.
	let showScoreSheet = $state(false);
	let showChat = $state(false);
	let showSettings = $state(false);

	let scoreSeats: SeatInfo[] = $derived(
		gameState.seats.map((s) => ({ seat: s.seat as SeatInfo['seat'], name: s.name }))
	);
	let scoreTotals: Totals = $derived(
		Object.fromEntries(gameState.seats.map((s) => [s.seat, s.score])) as Totals
	);
	// static single-hand history stand-in — score/game_end are still doc-only sketches
	// (ScoreSheet.svelte's own comment), same mock-data posture as the root demo page.
	let scoreHands: HandRecord[] = $derived([
		{
			handNo: gameState.handNo,
			dealer: gameState.dealer as HandRecord['dealer'],
			prevailing: gameState.prevailing,
			deltas: gameState.handResult?.payments ?? {}
		}
	]);

	let chatMessages: ChatEntry[] = $state([
		{ seat: 1, phrase: 'Good game', ts: Date.now() - 60_000 }
	]);
	function sendChat(phrase: string): void {
		chatMessages = [...chatMessages, { seat: 0, phrase, ts: Date.now() }];
	}

	let autoArm: AutoArm = $state({ noCalls: false, autoPassChow: false });
	let clientPrefs: ClientPrefs = $state({ soundEnabled: true, motion: 'system' });

	let toastQueue: ToastEntry[] = $state([]);
	function pushToast(message: string): void {
		toastQueue = [...toastQueue, createToast(message)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}

	// --- Live animation demo (this sub-task) ------------------------------------------------
	// A sandbox independent of the 3 static scenarios above: proves the positional
	// slot-identity mechanics (tile-slots.ts, docs/03-frontend.md §4) and the
	// transform/opacity-only transition contract (§2) actually work end to end, rather than
	// being implemented but unreachable. No JS ticker anywhere here — every animation is a CSS
	// transition/animation driven by a class or DOM-insertion, and `ontransitionend` (not a
	// timer standing in for the animation) is what commits the data change once a flight
	// actually finishes.
	let showAnimationDemo = $state(false);

	const DEMO_REVEAL_POOL: TileCode[] = ['5s', '3p', '7m', 'z1', '9p', 'z5', '4s', '2m'];
	let demoRevealIndex = $state(0);
	function nextRevealedTile(): TileCode {
		const code = DEMO_REVEAL_POOL[demoRevealIndex % DEMO_REVEAL_POOL.length];
		demoRevealIndex += 1;
		return code;
	}

	let demoOpponentSlots: SlotState = $state(initialSlotState(13));
	let demoOpponentDiscards: TileCode[] = $state([]);
	let demoOpponentMelds: MockMeld[] = $state([]);
	let leavingOpponentSlotKey: number | null = $state(null);
	let leavingOpponentTile: TileCode | null = $state(null);

	// same element (keyed by slot.key) throughout back -> revealed-and-leaving -> gone, per
	// §4's "element continuity for the CSS transition" -- appending the departed slot back at
	// its old (last) position rather than letting it disappear from the each-block early.
	let renderedOpponentSlots = $derived(
		leavingOpponentSlotKey !== null
			? [...demoOpponentSlots.slots, { key: leavingOpponentSlotKey }]
			: demoOpponentSlots.slots
	);

	function demoOpponentDraw(): void {
		demoOpponentSlots = pushDrawnSlot(demoOpponentSlots);
	}

	function demoOpponentDiscard(): void {
		if (leavingOpponentSlotKey !== null) return; // one flight at a time
		if (demoOpponentSlots.slots.length === 0) return;
		const { left, remaining } = popSlotForDiscard(demoOpponentSlots);
		leavingOpponentTile = nextRevealedTile(); // morphs face-up immediately (§4)
		leavingOpponentSlotKey = left.key;
		demoOpponentSlots = remaining;
	}

	function commitOpponentDiscard(): void {
		if (leavingOpponentSlotKey === null || leavingOpponentTile === null) return;
		demoOpponentDiscards = [...demoOpponentDiscards, leavingOpponentTile];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
	}

	function demoOpponentConcealedKong(): void {
		if (demoOpponentSlots.slots.length < 4) return;
		const { remaining } = popSlotsForConcealedKong(demoOpponentSlots);
		demoOpponentSlots = remaining;
		// morphs in place -- no flight, the tiles never leave the seat (§4).
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'concealed_kong', tiles: ['1m', '1m', '1m', '1m'] }
		];
	}

	function demoOpponentClaim(): void {
		// last discarded tile claimed into an exposed pung -- the discard-pool -> meld flight
		// path, independent of the concealed-slot logic above (this tile is already revealed).
		if (demoOpponentDiscards.length === 0) return;
		const claimed = demoOpponentDiscards[demoOpponentDiscards.length - 1];
		demoOpponentDiscards = demoOpponentDiscards.slice(0, -1);
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'pung', tiles: [claimed, claimed, claimed], fromSeat: 0 }
		];
	}

	interface DemoTile {
		id: number;
		code: TileCode;
	}
	let demoTileIdSeed = 0;
	function demoTile(code: TileCode): DemoTile {
		demoTileIdSeed += 1;
		return { id: demoTileIdSeed, code };
	}
	let demoYourHand: DemoTile[] = $state([
		demoTile('1m'),
		demoTile('9s'),
		demoTile('z5'),
		demoTile('3p'),
		demoTile('7m')
	]);
	let demoYourDiscards: DemoTile[] = $state([]);
	let leavingYourTileId: number | null = $state(null);

	function demoYourDiscard(id: number): void {
		if (leavingYourTileId !== null) return;
		leavingYourTileId = id;
	}

	function commitYourDiscard(): void {
		if (leavingYourTileId === null) return;
		const tile = demoYourHand.find((t) => t.id === leavingYourTileId);
		demoYourHand = demoYourHand.filter((t) => t.id !== leavingYourTileId);
		if (tile) demoYourDiscards = [...demoYourDiscards, tile];
		leavingYourTileId = null;
	}

	function resetAnimationDemo(): void {
		demoOpponentSlots = initialSlotState(13);
		demoOpponentDiscards = [];
		demoOpponentMelds = [];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
		demoYourHand = [demoTile('1m'), demoTile('9s'), demoTile('z5'), demoTile('3p'), demoTile('7m')];
		demoYourDiscards = [];
		leavingYourTileId = null;
	}
</script>

{#snippet opponentRegion(seat: MockSeatState, position: 'across' | 'left' | 'right')}
	<section
		class="seat-region seat-region--{position}"
		class:seat-region--turn={seat.seat === gameState.turn}
		aria-label="{seat.name}'s seat"
	>
		<header class="seat-meta">
			<span class="seat-name">{seat.name}</span>
			<span class="seat-wind" title="seat wind">{seatWind(seat.seat)}</span>
			{#if seat.seat === gameState.dealer}<span class="dealer-badge" title="Dealer">D</span>{/if}
			{#if seat.seat === gameState.turn}<span class="turn-badge" title="Current turn">turn</span
				>{/if}
			<span class="seat-score">{seat.score}</span>
		</header>

		<div class="seat-hand-strip seat-hand-strip--{position}">
			{#if seat.flowers.length}
				<div class="tile-row flower-row" aria-label="{seat.name}'s flowers">
					{#each seat.flowers as code, i (i)}
						<div class="mini-tile"><TileFace {code} /></div>
					{/each}
				</div>
			{/if}

			<div class="tile-row backs-row" aria-label="{seat.concealedCount} concealed tiles">
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
			</div>

			{#if seat.melds.length}
				<div class="tile-row meld-row" aria-label="{seat.name}'s melds">
					{#each seat.melds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (ti)}
								<div class="mini-tile">
									<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div
			class="discard-pool discard-pool--{position}"
			role="list"
			aria-label="{seat.name}'s discards"
		>
			{#each seat.discards as code, i (i)}
				<div class="discard-tile" role="listitem"><TileFace {code} /></div>
			{/each}
		</div>
	</section>
{/snippet}

<h1 class="sr-only">Table</h1>

<div class="table-page">
	<header class="dev-toolbar">
		<div class="scenario-picker" role="group" aria-label="Mock scenario">
			{#each MOCK_SCENARIOS as scenario (scenario.id)}
				<button
					type="button"
					class="scenario-btn"
					class:active={scenario.id === scenarioId}
					aria-pressed={scenario.id === scenarioId}
					onclick={() => (scenarioId = scenario.id)}
				>
					{scenario.label}
				</button>
			{/each}
		</div>

		<div class="chrome-toggles">
			<button type="button" onclick={() => (showScoreSheet = !showScoreSheet)}>Score sheet</button>
			<button type="button" onclick={() => (showChat = !showChat)}>Chat</button>
			<button type="button" onclick={() => (showSettings = !showSettings)}>Settings</button>
			<button type="button" onclick={() => pushToast('Reconnecting…')}>Toast</button>
			<button type="button" onclick={() => (showAnimationDemo = !showAnimationDemo)}
				>Animate a turn</button
			>
		</div>
	</header>

	<div class="table-tilt">
		<div class="table-surface" data-testid="table-scene">
			{@render opponentRegion(seatAt(2), 'across')}
			{@render opponentRegion(seatAt(3), 'left')}
			{@render opponentRegion(seatAt(1), 'right')}

			<div class="center-info" aria-label="Table status">
				<p class="wall-count">Wall <strong>{gameState.wallCount}</strong></p>
				<p>Prevailing <strong>{WIND_LABEL[gameState.prevailing]}</strong></p>
				<p>Dealer <strong>{gameState.seats[gameState.dealer].name}</strong></p>
				<p>Turn <strong>{gameState.seats[gameState.turn].name}</strong></p>
			</div>

			<section class="seat-region seat-region--self" aria-label="Your hand">
				<header class="seat-meta">
					<span class="seat-name">{seatAt(0).name}</span>
					<span class="seat-wind" title="seat wind">{seatWind(seatAt(0).seat)}</span>
					{#if seatAt(0).seat === gameState.dealer}<span class="dealer-badge" title="Dealer">D</span
						>{/if}
					{#if seatAt(0).seat === gameState.turn}<span class="turn-badge" title="Current turn"
							>turn</span
						>{/if}
					<span class="seat-score">{seatAt(0).score}</span>
				</header>

				<div class="your-hand">
					{#if seatAt(0).flowers.length}
						<div class="tile-row flower-row" aria-label="Your flowers">
							{#each seatAt(0).flowers as code, i (i)}
								<div class="mini-tile"><TileFace {code} /></div>
							{/each}
						</div>
					{/if}

					{#if seatAt(0).melds.length}
						<div class="tile-row meld-row" aria-label="Your melds">
							{#each seatAt(0).melds as meld, mi (mi)}
								<div class="meld">
									{#each meld.tiles as code, ti (ti)}
										<div class="mini-tile">
											<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
										</div>
									{/each}
								</div>
							{/each}
						</div>
					{/if}

					<div class="hand-row" aria-label="Your concealed hand">
						{#each seatAt(0).concealedHand ?? [] as code, i (i)}
							<div class="hand-tile"><TileFace {code} /></div>
						{/each}
						{#if seatAt(0).drawn}
							<div class="hand-tile hand-tile--drawn"><TileFace code={seatAt(0).drawn} /></div>
						{/if}
					</div>
				</div>

				<div class="discard-pool discard-pool--self" role="list" aria-label="Your discards">
					{#each seatAt(0).discards as code, i (i)}
						<div class="discard-tile" role="listitem"><TileFace {code} /></div>
					{/each}
				</div>
			</section>
		</div>
	</div>

	{#if claimOptions}
		<div class="claim-overlay" data-testid="claim-overlay">
			<TimerRing durationMs={gameState.claimWindow?.durationMs ?? 0} />
			<ClaimButtons options={claimOptions} onChoose={chooseClaim} />
			{#if lastClaimChoice}
				<p class="sr-only" data-testid="claim-choice">chose: {lastClaimChoice.kind}</p>
			{/if}
		</div>
	{/if}

	{#if gameState.handResult?.outcome === 'win'}
		<div class="faan-overlay" data-testid="faan-overlay">
			<FaanBreakdown
				winner={gameState.handResult.winner as 0 | 1 | 2 | 3}
				winningHand={gameState.handResult.winningHand ?? []}
				patterns={gameState.handResult.patterns ?? []}
				totalFaan={gameState.handResult.totalFaan ?? 0}
				payments={gameState.handResult.payments ?? {}}
			/>
		</div>
	{/if}

	{#if showScoreSheet}
		<div class="panel-overlay">
			<button type="button" class="panel-close" onclick={() => (showScoreSheet = false)}
				>Close</button
			>
			<ScoreSheet seats={scoreSeats} totals={scoreTotals} hands={scoreHands} />
		</div>
	{/if}

	{#if showChat}
		<div class="panel-overlay">
			<button type="button" class="panel-close" onclick={() => (showChat = false)}>Close</button>
			<Chat messages={chatMessages} onSend={sendChat} />
		</div>
	{/if}

	{#if showSettings}
		<div class="panel-overlay">
			<button type="button" class="panel-close" onclick={() => (showSettings = false)}>Close</button
			>
			<Settings
				{autoArm}
				prefs={clientPrefs}
				onAutoArmChange={(next) => (autoArm = next)}
				onPrefsChange={(next) => (clientPrefs = next)}
			/>
		</div>
	{/if}

	{#if showAnimationDemo}
		<div class="panel-overlay" data-testid="animation-demo">
			<div class="animation-demo">
				<button type="button" class="panel-close" onclick={() => (showAnimationDemo = false)}
					>Close</button
				>
				<h2>Animate a turn</h2>
				<p class="demo-hint">
					Sandboxed mock, independent of the scenarios above — proves the positional slot-identity
					mechanics and CSS-only transitions.
				</p>

				<section aria-label="Opponent seat">
					<h3>Bob (opponent)</h3>
					<div class="tile-row backs-row" aria-label="Bob's concealed tiles">
						{#each renderedOpponentSlots as slot (slot.key)}
							<div
								class="mini-tile back demo-slot"
								class:demo-tile-leaving={slot.key === leavingOpponentSlotKey}
								ontransitionend={slot.key === leavingOpponentSlotKey
									? commitOpponentDiscard
									: undefined}
							>
								<TileFace code={slot.key === leavingOpponentSlotKey ? leavingOpponentTile : null} />
							</div>
						{/each}
					</div>
					{#if demoOpponentMelds.length}
						<div class="tile-row meld-row" aria-label="Bob's melds">
							{#each demoOpponentMelds as meld, mi (mi)}
								<div class="meld demo-meld-entering">
									{#each meld.tiles as code, ti (ti)}
										<div class="mini-tile">
											<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
										</div>
									{/each}
								</div>
							{/each}
						</div>
					{/if}
					<div class="discard-pool" role="list" aria-label="Bob's discards">
						{#each demoOpponentDiscards as code, i (i)}
							<div class="discard-tile" role="listitem"><TileFace {code} /></div>
						{/each}
					</div>
					<div class="demo-actions">
						<button type="button" onclick={demoOpponentDraw}>Draw</button>
						<button
							type="button"
							onclick={demoOpponentDiscard}
							disabled={leavingOpponentSlotKey !== null || demoOpponentSlots.slots.length === 0}
						>
							Discard
						</button>
						<button
							type="button"
							onclick={demoOpponentConcealedKong}
							disabled={demoOpponentSlots.slots.length < 4}
						>
							Concealed kong
						</button>
						<button
							type="button"
							onclick={demoOpponentClaim}
							disabled={demoOpponentDiscards.length === 0}
						>
							You claim last discard (pung)
						</button>
					</div>
				</section>

				<section aria-label="Your seat">
					<h3>You</h3>
					<div class="hand-row" aria-label="Your demo hand" data-testid="demo-your-hand">
						{#each demoYourHand as tile (tile.id)}
							<button
								type="button"
								class="hand-tile demo-hand-tile"
								class:demo-tile-leaving={tile.id === leavingYourTileId}
								disabled={leavingYourTileId !== null}
								aria-label="Discard {tile.code}"
								onclick={() => demoYourDiscard(tile.id)}
								ontransitionend={tile.id === leavingYourTileId ? commitYourDiscard : undefined}
							>
								<TileFace code={tile.code} />
							</button>
						{/each}
					</div>
					<div
						class="discard-pool discard-pool--self"
						role="list"
						aria-label="Your discards"
						data-testid="demo-your-discards"
					>
						{#each demoYourDiscards as tile (tile.id)}
							<div class="discard-tile" role="listitem"><TileFace code={tile.code} /></div>
						{/each}
					</div>
				</section>

				<button type="button" class="demo-reset" onclick={resetAnimationDemo}>Reset demo</button>
			</div>
		</div>
	{/if}

	<div class="toast-stack">
		{#each toastQueue as toast (toast.id)}
			<Toast
				message={toast.message}
				durationMs={toast.durationMs}
				onDismiss={() => dismissToast(toast.id)}
			/>
		{/each}
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.table-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-height: 100dvh;
		padding: var(--space-3);
	}

	.dev-toolbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-3);
		z-index: var(--z-hud);
	}

	.scenario-picker,
	.chrome-toggles {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.scenario-btn,
	.chrome-toggles button {
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
	}

	.scenario-btn.active {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-text);
		font-weight: 600;
	}

	.table-tilt {
		flex: 1;
		@include layout.table-perspective;
	}

	.table-surface {
		@include layout.seat-region-grid;
		height: 100%;
		min-height: 420px;
		padding: var(--space-3);
		// faint overhead-light falloff on the lacquered surface — a believable material cue,
		// not a texture asset; stays quiet enough that tiles (the brightest thing on screen,
		// §1) are unaffected.
		background:
			radial-gradient(ellipse 80% 60% at 50% 10%, rgb(255 255 255 / 0.035), transparent 65%),
			var(--color-surface);
		border-radius: var(--radius-md);
		transform: rotateX(6deg);
		transform-style: preserve-3d;

		@include layout.phone-only {
			transform: none; // tilt reads as decoration, not worth the layout cost on phone widths
		}
	}

	.seat-region {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
	}

	.seat-region--across {
		grid-area: across;
	}

	.seat-region--left {
		grid-area: left;
	}

	.seat-region--right {
		grid-area: right;
	}

	.seat-region--self {
		grid-area: self;
	}

	.seat-region--turn {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
		border-radius: var(--radius-sm);
	}

	.seat-meta {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.seat-name {
		font-weight: 600;
	}

	.seat-wind {
		color: var(--color-text-muted);
	}

	.dealer-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: 50%;
		background: var(--color-accent);
		color: var(--color-text);
		font-size: 0.7rem;
		font-weight: 700;
	}

	.turn-badge {
		color: var(--color-accent);
		font-size: var(--font-size-sm);
		text-transform: uppercase;
	}

	.seat-score {
		margin-inline-start: auto;
		font-variant-numeric: tabular-nums;
		color: var(--color-text-muted);
	}

	.seat-hand-strip {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.tile-row {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}

	.mini-tile {
		height: clamp(24px, 4vw, 36px);
	}

	.mini-tile :global(.tile-face) {
		height: 100%;
	}

	.meld {
		display: flex;
		gap: 1px;
		margin-inline-end: var(--space-2);
	}

	// vertical strip along the table edge (docs/03-frontend.md §3): `writing-mode` alone reflows
	// the flex axes (a row's main axis becomes the block-progression axis) so the box's own
	// width/height already account for the vertical footprint, unlike `transform: rotate()`,
	// which only repaints the box in place and leaves the parent grid cell sized for the
	// original unrotated (horizontal) footprint — that mismatch is what let the strip's content
	// escape `.seat-region--left/--right` into whatever sat past the grid's edge.
	.seat-hand-strip--left {
		@include layout.tablet-up {
			writing-mode: vertical-lr;
		}
	}

	.seat-hand-strip--right {
		@include layout.tablet-up {
			writing-mode: vertical-rl;
		}
	}

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 1fr));
		gap: 2px;
		max-width: 14rem;
	}

	.discard-pool--self {
		max-width: 20rem;
	}

	.discard-tile {
		height: clamp(22px, 3.5vw, 32px);
	}

	.discard-tile :global(.tile-face) {
		height: 100%;
	}

	.center-info {
		grid-area: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		text-align: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.center-info strong {
		color: var(--color-text);
	}

	.your-hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.hand-row {
		display: flex;
		gap: 2px;
	}

	.hand-tile {
		height: clamp(48px, 9vw, 84px);
	}

	.hand-tile :global(.tile-face) {
		height: 100%;
	}

	.hand-tile--drawn {
		margin-inline-start: var(--space-4);
	}

	.claim-overlay {
		position: fixed;
		inset-inline: 0;
		bottom: var(--space-8);
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		z-index: var(--z-overlay);
		pointer-events: none;
	}

	.claim-overlay :global(.timer-ring) {
		pointer-events: auto;
	}

	.faan-overlay,
	.panel-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.5);
		z-index: var(--z-modal);
		padding: var(--space-3);
	}

	.panel-close {
		position: absolute;
		top: var(--space-4);
		right: var(--space-4);
		min-height: 44px;
		min-width: 44px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;
	}

	.toast-stack {
		position: fixed;
		top: var(--space-4);
		right: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-width: 20rem;
		z-index: var(--z-overlay);
	}

	// --- Live animation demo (docs/03-frontend.md §2: transform/opacity only, no JS ticker) ---

	.animation-demo {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 32rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		border-radius: var(--radius-md);
	}

	.demo-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.demo-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.demo-actions button,
	.demo-reset {
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: var(--color-surface);
		color: var(--color-text);
		font: inherit;
		cursor: pointer;

		&:disabled {
			opacity: 0.5;
			cursor: not-allowed;
		}
	}

	.demo-hand-tile {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;

		&:disabled {
			cursor: not-allowed;
		}
	}

	// the departing slot/tile: transform+opacity only, per §2 -- no layout-affecting property
	// animates, so this never triggers reflow on the ~150-element hand/pool it sits inside.
	.demo-tile-leaving {
		transition:
			transform 260ms ease-in,
			opacity 260ms ease-in;
		transform: translateY(24px) scale(0.85);
		opacity: 0;
	}

	// a claimed/kong meld is a freshly-inserted DOM node, so this animation plays automatically
	// on insert with no JS trigger needed at all.
	.demo-meld-entering {
		animation: demo-meld-in 220ms ease-out;
	}

	@keyframes demo-meld-in {
		from {
			opacity: 0;
			transform: translateY(-10px) scale(0.9);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}

	// reduced motion: skip the visible motion but keep a near-instant transition running --
	// `ontransitionend` is what commits the data change (see the script section above), so
	// `transition: none` here would leave the demo permanently stuck mid-flight instead of
	// just snapping instead of sliding.
	@media (prefers-reduced-motion: reduce) {
		.demo-tile-leaving {
			transition-duration: 1ms;
			transform: none;
		}

		.demo-meld-entering {
			animation-duration: 1ms;
		}
	}

	// sub-768px collapse (docs/03-frontend.md §3): opponent backs to a thin overlapping strip,
	// discard pools to horizontal scroll, your hand pinned to the safe-area bottom.
	@include layout.phone-only {
		.seat-hand-strip--left,
		.seat-hand-strip--right,
		.seat-hand-strip--across {
			flex-direction: row;
		}

		.backs-row .mini-tile {
			margin-inline-end: -14px; // overlapping-backs strip, count-only

			&:last-child {
				margin-inline-end: 0;
			}
		}

		.discard-pool {
			grid-template-columns: none;
			grid-auto-flow: column;
			grid-auto-columns: minmax(22px, 28px);
			overflow-x: auto;
			max-width: 100%;
		}

		.seat-region--self {
			position: fixed;
			inset-inline: 0;
			bottom: 0;
			background: var(--color-surface);
			border-top: 1px solid var(--color-border);
			padding: var(--space-2) var(--space-2) max(var(--space-2), env(safe-area-inset-bottom));
			z-index: var(--z-hud);
		}

		.table-surface {
			padding-bottom: 30vh; // reserve room under the fixed self region above
		}

		.hand-tile {
			height: clamp(44px, 12vw, 60px);
		}
	}
</style>
