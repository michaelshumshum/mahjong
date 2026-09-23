<script lang="ts">
	import TileFace from './TileFace.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import { seatWind, WIND_LABEL, WIND_CHAR } from './wind';

	let {
		seat,
		position,
		dealer,
		turn
	}: { seat: MockSeatState; position: 'across' | 'left' | 'right'; dealer: Seat; turn: number } =
		$props();
</script>

<section
	class="seat-region seat-region--{position}"
	class:seat-region--turn={seat.seat === turn}
	aria-label="{seat.name}'s seat"
>
	<header class="seat-meta">
		<span class="seat-name">{seat.name}</span>
		<span class="seat-wind" aria-label="{WIND_LABEL[seatWind(seat.seat, dealer)]} wind"
			>{WIND_CHAR[seatWind(seat.seat, dealer)]}</span
		>
		{#if seat.seat === dealer}<span class="dealer-badge" title="Dealer">莊</span>{/if}
		{#if seat.status === 'bot'}<span class="bot-badge" title="Bot-controlled seat">Bot</span>{/if}
		<span class="seat-score">{seat.score}</span>
	</header>

	<div class="seat-hand-strip seat-hand-strip--{position}">
		{#if seat.concealedHand}
			<div class="tile-row backs-row" aria-label="{seat.name}'s concealed hand">
				{#each seat.concealedHand as code, i (i)}
					<div class="mini-tile"><TileFace {code} /></div>
				{/each}
			</div>
		{:else}
			<div class="tile-row backs-row" aria-label="{seat.concealedCount} concealed tiles">
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
			</div>
		{/if}

		{#if seat.flowers.length || seat.melds.length}
			<div class="tile-row meld-row" aria-label="{seat.name}'s melds">
				{#if seat.flowers.length}
					<div class="meld" aria-label="{seat.name}'s flowers">
						{#each seat.flowers as code, i (i)}
							<div class="mini-tile"><TileFace {code} /></div>
						{/each}
					</div>
				{/if}
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
</section>

<style lang="scss">
	@use '$lib/styles/layout';

	.seat-region {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
		min-height: 0;
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
		aspect-ratio: 1/1;
	}

	// bot-controlled seat (M4.5 practice mode) -- a persistent identity marker, not a transient
	// state like dealer/turn, so it reads as a quiet chip rather than borrowing --color-accent.
	.bot-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 1.25rem;
		padding: 0 0.4rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
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

	// tiles themselves rotated 90° to face the table, same physical read as a real side seat.
	// The mismatch that ruled out `transform: rotate()` on the *strip* above is still real, so
	// it isn't reused here at the tile level either: `.mini-tile` keeps its normal (unrotated)
	// box for layout purposes, already sized to the rotated footprint (width/height swapped from
	// the portrait default) — the swap is what the grid/flex ancestors measure. Only the
	// `.tile-face` inside is rotated, absolutely positioned off that stable box so the rotation
	// is paint-only and never changes what its ancestors reserve space for.
	.seat-hand-strip--left .mini-tile,
	.seat-hand-strip--right .mini-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(24px, 4vw, 36px);
			height: calc(clamp(24px, 4vw, 36px) * 3 / 4);
		}
	}

	.seat-hand-strip--left .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.seat-hand-strip--right .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	// sub-768px collapse (docs/03-frontend.md §3): opponent backs to a thin overlapping strip.
	@include layout.phone-only {
		.seat-hand-strip--left,
		.seat-hand-strip--right,
		.seat-hand-strip--across {
			flex-direction: row;
		}

		.backs-row .mini-tile.back {
			margin-inline-end: -14px; // overlapping-backs strip, count-only

			&:last-child {
				margin-inline-end: 0;
			}
		}
	}
</style>
