<script lang="ts">
	import TileFace from './TileFace.svelte';
	import { meldTileFace } from './meld-face';
	import SeatPlate from './SeatPlate.svelte';
	import BotBadge from './BotBadge.svelte';
	import SeatStatusChip from './SeatStatusChip.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import { seatWind, windWord, WIND_CHAR } from './wind';
	import { m } from '$lib/paraglide/messages.js';

	let {
		seat,
		position,
		dealer,
		turn,
		scoreDelta = null
	}: {
		seat: MockSeatState;
		position: 'across' | 'left' | 'right';
		dealer: Seat;
		turn: number;
		scoreDelta?: { value: number; key: number } | null;
	} = $props();
</script>

<section
	class="seat-region seat-region--{position}"
	class:seat-region--turn={seat.seat === turn}
	aria-label={m.opponentRegion_seatAriaLabel({ name: seat.name })}
>
	<SeatPlate
		name={seat.name}
		windChar={WIND_CHAR[seatWind(seat.seat, dealer)]}
		windAriaLabel={m.opponentRegion_windAriaLabel({ wind: windWord(seatWind(seat.seat, dealer)) })}
		isDealer={seat.seat === dealer}
		dealerTitle={m.opponentRegion_dealerBadgeTitle()}
		score={seat.score}
		isTurn={seat.seat === turn}
		{scoreDelta}
	>
		{#snippet badges()}
			{#if seat.status === 'bot'}<BotBadge level={seat.botLevel} />{/if}
			<SeatStatusChip status={seat.status} />
		{/snippet}
	</SeatPlate>

	<div class="seat-hand-strip seat-hand-strip--{position}">
		{#if seat.concealedHand}
			<div
				class="tile-row backs-row"
				aria-label={m.opponentRegion_concealedHandAriaLabel({ name: seat.name })}
			>
				{#each seat.concealedHand as code, i (i)}
					<div class="mini-tile"><TileFace {code} /></div>
				{/each}
			</div>
		{:else}
			<div
				class="tile-row backs-row"
				aria-label={m.opponentRegion_concealedTilesAriaLabel({ count: seat.concealedCount })}
			>
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
				<!-- phone: one back plus this count stands in for the whole strip -->
				<span class="backs-count" aria-hidden="true"
					>{m.opponentRegion_backsCount({ count: seat.concealedCount })}</span
				>
			</div>
		{/if}

		<div
			class="tile-row meld-row"
			class:meld-row--empty={!seat.flowers.length && !seat.melds.length}
			aria-label={m.opponentRegion_meldsAriaLabel({ name: seat.name })}
		>
			{#if seat.flowers.length}
				<div class="meld" aria-label={m.opponentRegion_flowersAriaLabel({ name: seat.name })}>
					{#each seat.flowers as code, i (i)}
						<div class="mini-tile"><TileFace {code} /></div>
					{/each}
				</div>
			{/if}
			{#each seat.melds as meld, mi (mi)}
				<div class="meld">
					{#each meld.tiles as code, ti (ti)}
						<div class="mini-tile">
							<TileFace code={meldTileFace(meld.kind, code, ti, meld.tiles.length)} />
						</div>
					{/each}
				</div>
			{/each}
		</div>
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

	.seat-hand-strip {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);

		@include layout.tablet-up {
			flex: 1;
			align-items: center;
		}
	}

	.tile-row {
		@include tile.tile-row;
	}

	.mini-tile {
		@include tile.mini-tile;
	}

	.meld {
		@include tile.meld;
		@include tile.meld-enter;
	}

	// the hand centres, melds stay at the seat's own left (inline start, which the strip rotates).
	.meld-row {
		@include tile.meld-row-reserved;

		@include layout.tablet-up {
			align-self: start;
		}
	}

	// writing-mode reflows the flex axes so width/height already reflect the vertical footprint --
	// unlike transform: rotate(), which repaints in place and let content escape the grid cell.
	.seat-hand-strip--left {
		@include layout.tablet-up {
			writing-mode: vertical-lr;
		}
	}

	// your hand turned 180deg: right to left, melds below toward the centre. faces stay upright.
	.seat-hand-strip--across {
		@include layout.tablet-up {
			direction: rtl;
		}
	}

	// rtl runs the inline axis bottom to top: the left seat turned 180deg, not mirrored.
	.seat-hand-strip--right {
		@include layout.tablet-up {
			writing-mode: vertical-rl;
			direction: rtl;
		}
	}

	// same avoid-rotating-the-sized-box principle as the strip above, one level deeper: .mini-tile
	// keeps an unrotated, pre-sized box; only .tile-face inside rotates, so it's paint-only.
	.seat-hand-strip--left .mini-tile,
	.seat-hand-strip--right .mini-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(24px, 4cqi, 36px);
			height: calc(clamp(24px, 4cqi, 36px) * 3 / 4);
		}
	}

	.seat-hand-strip--left .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4cqi, 36px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.seat-hand-strip--right .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4cqi, 36px);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	// side strips run vertically; wrapping would push the drawn tile into a second column
	.seat-hand-strip--left .backs-row,
	.seat-hand-strip--right .backs-row {
		@include layout.tablet-up {
			flex-wrap: nowrap;
		}
	}

	.backs-row .drawn-gap {
		margin-inline-start: var(--space-2);
	}

	.backs-count {
		display: none;
	}

	// sub-768px chip row: plate, one back + ×N, melds (second line only if they don't fit).
	// the other backs stay in the DOM (positional identity, frontend.md §4), only hidden.
	@include layout.phone-only {
		.seat-region {
			flex-flow: row wrap;
			align-items: center;
			gap: var(--space-1) var(--space-2);
			padding: var(--space-1) var(--space-2);
			// squared bottom: the seat's discard pool continues the chip below it.
			border-radius: var(--radius-md) var(--radius-md) 0 0;
			background: rgb(0 0 0 / 0.18);
		}

		// each meld (and the flower group) is its own flex item: flowers join the name line and a
		// meld wraps whole, never split across lines.
		.seat-hand-strip,
		.meld-row {
			display: contents;
		}

		.meld {
			margin-inline-end: 0;
		}

		// fixed width so the ×N counts line up down the three rows; long names truncate.
		.seat-region :global(.seat-plate) {
			flex: 0 0 8rem;
			gap: var(--space-1);
			min-width: 0;
		}

		.seat-region :global(.seat-name) {
			min-width: 0;
			overflow: hidden;
			text-overflow: ellipsis;
			white-space: nowrap;
		}

		// the one visible back matches the melds, so it never sets the plate line's height.
		.seat-region {
			--chip-tile-h: 28px;
		}

		.meld-row .mini-tile,
		.backs-row .mini-tile {
			height: var(--chip-tile-h);
		}

		.backs-row {
			flex-wrap: nowrap;
			align-items: center;
		}

		.backs-row .mini-tile.back ~ .mini-tile.back {
			display: none;
		}

		.backs-count {
			display: inline-block;
			margin-inline-start: var(--space-1);
			color: var(--color-text-muted);
			font-size: var(--font-size-sm);
			font-weight: 700;
			font-variant-numeric: tabular-nums;
		}
	}

	@include layout.phone-landscape {
		.seat-region {
			--chip-tile-h: calc(clamp(20px, 5.6dvh, 26px) * var(--tile-scale, 1));
		}
	}
</style>
