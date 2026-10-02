<script lang="ts">
	import TileFace from './TileFace.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import type { TileCode } from './tile-code';
	import { seatWind, windWord, WIND_CHAR } from './wind';
	import { m } from '$lib/paraglide/messages.js';

	interface OwnHandTile {
		key: string;
		code: TileCode;
		tileId: number | null;
		drawn: boolean;
	}

	interface DeclareOption {
		key: string;
		label: string;
		onClick: () => void;
	}

	let {
		seat,
		spectating,
		dealer,
		turn,
		turnDurationMs,
		isMock,
		ownHandTiles,
		discardableTileIds,
		onDiscard,
		declareOptions
	}: {
		seat: MockSeatState;
		spectating: boolean;
		dealer: Seat;
		turn: number;
		turnDurationMs: number | null;
		isMock: boolean;
		ownHandTiles: OwnHandTile[];
		discardableTileIds: Set<number>;
		onDiscard: (tileId: number) => void;
		declareOptions: DeclareOption[];
	} = $props();
</script>

<section
	class="seat-region seat-region--self"
	aria-label={spectating
		? m.yourSeatRegion_seatAriaLabel({ name: seat.name })
		: m.yourSeatRegion_yourHandAriaLabel()}
>
	<header class="seat-meta">
		<span class="seat-name">{seat.name}</span>
		<span
			class="seat-wind"
			aria-label={m.yourSeatRegion_windAriaLabel({ wind: windWord(seatWind(seat.seat, dealer)) })}
			>{WIND_CHAR[seatWind(seat.seat, dealer)]}</span
		>
		{#if seat.seat === dealer}<span class="dealer-badge" title={m.yourSeatRegion_dealerBadgeTitle()}
				>莊</span
			>{/if}
		<div class="turn-timer">
			{#if turnDurationMs !== null}
				{#key turn}
					<TimerRing durationMs={turnDurationMs} size={24} />
				{/key}
			{/if}
		</div>
		<span class="seat-score">{seat.score}</span>
	</header>

	<div class="your-hand">
		{#if seat.flowers.length || seat.melds.length}
			<div
				class="tile-row meld-row"
				aria-label={spectating
					? m.yourSeatRegion_meldsAriaLabel({ name: seat.name })
					: m.yourSeatRegion_yourMeldsAriaLabel()}
			>
				{#if seat.flowers.length}
					<div
						class="meld"
						aria-label={spectating
							? m.yourSeatRegion_flowersAriaLabel({ name: seat.name })
							: m.yourSeatRegion_yourFlowersAriaLabel()}
					>
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

		<!-- spectators get the opponents' tile size: no seat here is "yours" -->
		{#if spectating && seat.concealedHand}
			<div
				class="tile-row backs-row"
				aria-label={m.yourSeatRegion_concealedHandAriaLabel({ name: seat.name })}
			>
				{#each seat.concealedHand ?? [] as code, i (i)}
					<div class="mini-tile"><TileFace {code} /></div>
				{/each}
			</div>
		{:else if spectating}
			<div
				class="tile-row backs-row"
				aria-label={m.yourSeatRegion_concealedTilesAriaLabel({ count: seat.concealedCount })}
			>
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
			</div>
		{:else}
			<div class="hand-row" aria-label={m.yourSeatRegion_yourConcealedHandAriaLabel()}>
				{#each ownHandTiles as tile (tile.key)}
					{#if !isMock && tile.tileId !== null && discardableTileIds.has(tile.tileId)}
						<button
							type="button"
							class="hand-tile hand-tile-btn"
							class:hand-tile--drawn={tile.drawn}
							aria-label={m.yourSeatRegion_discardTileAriaLabel({ tile: tile.code })}
							onclick={() => onDiscard(tile.tileId as number)}
						>
							<TileFace code={tile.code} />
						</button>
					{:else}
						<div class="hand-tile" class:hand-tile--drawn={tile.drawn}>
							<TileFace code={tile.code} />
						</div>
					{/if}
				{/each}
			</div>
		{/if}

		{#if declareOptions.length}
			<div
				class="declare-actions"
				role="group"
				aria-label={m.yourSeatRegion_declareOptionsAriaLabel()}
			>
				{#each declareOptions as opt (opt.key)}
					<button type="button" onclick={opt.onClick}>{opt.label}</button>
				{/each}
			</div>
		{/if}
	</div>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';
	@use '$lib/styles/tile';

	.seat-region {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
		min-height: 0;
	}

	.seat-region--self {
		grid-area: self;
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

	// fixed footprint so the header doesn't reflow -- .seat-score's margin-inline-start: auto
	// shifts with any preceding sibling that mounts/unmounts, and this toggles every turn.
	.turn-timer {
		width: 24px;
		height: 24px;
		pointer-events: none;
	}

	.dealer-badge {
		@include tile.dealer-badge;
	}

	.seat-score {
		@include tile.seat-score;
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

	// same box as the plain .hand-tile div -- a button reset, not a second style.
	.hand-tile-btn {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;

		&:focus-visible {
			outline: 2px solid var(--color-accent);
			outline-offset: 2px;
		}
	}

	.declare-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);

		button {
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-3);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-primary;

			// btn-primary's :active translateY(3px) moves the button out from under mouseup's
			// hit-test, so the click lands on the row's own div and the action never sends.
			&:active:not(:disabled) {
				transform: none;
			}
		}
	}

	// sub-768px collapse: pinned to the safe-area bottom, horizontal scroll once a hand overflows.
	@include layout.phone-only {
		@include tile.backs-row-overlap;

		.seat-region--self {
			position: fixed;
			inset-inline: 0;
			bottom: 0;
			background: var(--color-surface);
			border-top: 1px solid var(--color-border);
			padding: var(--space-2) var(--space-2) max(var(--space-2), env(safe-area-inset-bottom));
			z-index: var(--z-hud);
		}

		.hand-tile {
			height: clamp(44px, 12vw, 60px);
		}

		// .seat-region--self is position: fixed (no scrollable ancestor) -- without this, tiles
		// past the edge are unreachable rather than scrolled-to.
		.hand-row {
			overflow-x: auto;
		}
	}
</style>
