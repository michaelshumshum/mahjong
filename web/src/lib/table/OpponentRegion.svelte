<script lang="ts">
	import TileFace from './TileFace.svelte';
	import SeatPlate from './SeatPlate.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import { seatWind, windWord, WIND_CHAR } from './wind';
	import { m } from '$lib/paraglide/messages.js';

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
	>
		{#snippet badges()}
			{#if seat.status === 'bot'}<span class="bot-badge" title={m.opponentRegion_botBadgeTitle()}
					>{m.opponentRegion_botBadgeLabel()}</span
				>{/if}
			{#if seat.status === 'disconnected'}<span
					class="status-chip status-chip--away"
					title={m.opponentRegion_awayChipTitle()}>{m.opponentRegion_awayChipLabel()}</span
				>{:else if seat.status === 'autoplay'}<span
					class="status-chip status-chip--autoplay"
					title={m.opponentRegion_autoplayChipTitle()}>{m.opponentRegion_autoplayChipLabel()}</span
				>{/if}
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
							<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
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

	// disconnected/autoplay are transient (unlike the bot badge's fixed identity), so they get a
	// tint, not the bot badge's neutral chrome: error for a seat in trouble, accent for autoplay.
	.status-chip {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 1.25rem;
		padding: 0 0.4rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.status-chip--away {
		border: 1px solid var(--color-status-error);
		color: var(--color-status-error);
		background: rgb(0 0 0 / 0.15);
	}

	.status-chip--autoplay {
		border: 1px solid var(--color-accent);
		color: var(--color-accent);
		background: rgb(0 0 0 / 0.15);
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

	.meld-row {
		@include tile.meld-row-reserved;
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
