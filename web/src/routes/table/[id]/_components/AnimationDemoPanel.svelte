<script lang="ts">
	// A sandbox independent of the 3 static mock scenarios: proves the positional
	// slot-identity mechanics (tile-slots.ts, docs/03-frontend.md §4) and the
	// transform/opacity-only transition contract (§2) actually work end to end, rather than
	// being implemented but unreachable. No JS ticker anywhere here — every animation is a CSS
	// transition/animation driven by a class or DOM-insertion, and `ontransitionend` (not a
	// timer standing in for the animation) is what commits the data change once a flight
	// actually finishes.
	import TileFace from '$lib/table/TileFace.svelte';
	import type { MockMeld } from '$lib/table/mock-game-state';
	import type { TileCode } from '$lib/table/tile-code';
	import {
		initialSlotState,
		popSlotForDiscard,
		popSlotsForConcealedKong,
		pushDrawnSlot,
		type SlotState
	} from '$lib/table/tile-slots';
	import CloseButton from '$lib/ui/CloseButton.svelte';

	let { onClose }: { onClose: () => void } = $props();

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

<div class="panel-overlay" data-testid="animation-demo">
	<div class="animation-demo">
		<CloseButton onclick={onClose} />
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

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/tile';

	// tile-display primitives shared with the real seat regions (docs/03-frontend.md §7.1's
	// _tile.scss) -- this sandbox has no game-state dependency on the real table surface, so it
	// still can't share OpponentRegion/YourSeatRegion's scoped selectors directly, but the shape
	// of each rule is identical, so it goes through the same mixins.
	.panel-overlay {
		@include buttons.modal-scrim;
	}

	.tile-row {
		@include tile.tile-row;
	}

	.mini-tile {
		@include tile.mini-tile;
	}

	.meld {
		@include tile.meld;
	}

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 28px));
		justify-content: start;
		gap: 2px;
		max-width: 14rem;
	}

	.discard-tile {
		@include tile.mini-tile(clamp(22px, 3.5vw, 32px));
	}

	.hand-row {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}

	.hand-tile {
		@include tile.mini-tile;
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
		@include buttons.panel-elevated;
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
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
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
</style>
