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
	@use '$lib/styles/tile';

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
		@include tile.seat-meta;
	}

	.seat-name {
		@include tile.seat-name;
	}

	.seat-wind {
		@include tile.seat-wind;
	}

	.dealer-badge {
		@include tile.dealer-badge;
	}

	// persistent identity marker, not transient like dealer/turn -- a quiet chip, not --color-accent.
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
		font-size: var(--font-size-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.seat-score {
		@include tile.seat-score;
	}

	.seat-hand-strip {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
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

	// writing-mode reflows the flex axes so width/height already reflect the vertical footprint --
	// unlike transform: rotate(), which repaints in place and let content escape the grid cell.
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

	// same avoid-rotating-the-sized-box principle as the strip above, one level deeper: .mini-tile
	// keeps an unrotated, pre-sized box; only .tile-face inside rotates, so it's paint-only.
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

	// sub-768px collapse: opponent backs to a thin overlapping strip.
	@include layout.phone-only {
		.seat-hand-strip--left,
		.seat-hand-strip--right,
		.seat-hand-strip--across {
			flex-direction: row;
		}

		@include tile.backs-row-overlap;
	}
</style>
