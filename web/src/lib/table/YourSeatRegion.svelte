<script lang="ts">
	import TileFace from './TileFace.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import type { TileCode } from './tile-code';
	import { tileName, tileOptionAriaLabel } from './tile-name';
	import TileOptionLabel from '$lib/ui/TileOptionLabel.svelte';
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
		tiles?: TileCode[];
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
	<!-- melds above the name, toward the centre -->
	<div
		class="tile-row meld-row"
		class:meld-row--empty={!seat.flowers.length && !seat.melds.length}
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
							aria-label={m.yourSeatRegion_discardTileAriaLabel({ tile: tileName(tile.code) })}
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
					<button
						type="button"
						aria-label={opt.tiles?.length ? tileOptionAriaLabel(opt.label, opt.tiles) : undefined}
						onclick={opt.onClick}
					>
						<TileOptionLabel label={opt.label} tiles={opt.tiles} />
					</button>
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

	// hand tiles size from this box's width (cqi), not the viewport.
	.seat-region--self {
		grid-area: self;
		container-type: inline-size;
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

	.meld-row {
		@include tile.meld-row-reserved;
	}

	.your-hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	// 13 tiles + the drawn one fit the container: shrink to fit down to the 44px touch target
	// (docs/frontend.md §3), then overlap via negative margins instead of shrinking further.
	.hand-row {
		--hand-gap: 2px;
		--hand-drawn-gap: var(--space-4);
		--hand-fit-w: calc((100cqi - 13 * var(--hand-gap) - var(--hand-drawn-gap)) / 14);
		--hand-tile-w: clamp(44px, var(--hand-fit-w), 63px);
		--hand-step: min(
			var(--hand-gap),
			calc((100cqi - var(--hand-drawn-gap) - 14 * var(--hand-tile-w)) / 13)
		);
		display: flex;
	}

	.hand-tile {
		flex: none;
		width: var(--hand-tile-w);
		height: calc(var(--hand-tile-w) * 4 / 3);
	}

	.hand-tile + .hand-tile {
		margin-inline-start: var(--hand-step);
	}

	.hand-tile :global(.tile-face) {
		height: 100%;
	}

	.hand-row .hand-tile--drawn {
		margin-inline-start: calc(var(--hand-drawn-gap) + var(--hand-step));
	}

	// same box as the plain .hand-tile div -- a button reset, not a second style.
	.hand-tile-btn {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;
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

	// sub-768px collapse: sticky to the safe-area bottom. it keeps its own grid row, so nothing
	// above needs padding reserved under it (unlike position: fixed).
	@include layout.phone-only {
		@include tile.backs-row-overlap;

		.seat-region--self {
			position: sticky;
			bottom: 0;
			background: var(--color-surface);
			border-top: 1px solid var(--color-border);
			padding: var(--space-2) var(--space-2) max(var(--space-2), env(safe-area-inset-bottom));
			z-index: var(--z-hud);
		}
	}
</style>
