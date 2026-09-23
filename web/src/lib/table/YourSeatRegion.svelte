<script lang="ts">
	import TileFace from './TileFace.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import type { TileCode } from './tile-code';
	import { seatWind, WIND_LABEL, WIND_CHAR } from './wind';

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
	aria-label={spectating ? `${seat.name}'s seat` : 'Your hand'}
>
	<header class="seat-meta">
		<span class="seat-name">{seat.name}</span>
		<span class="seat-wind" aria-label="{WIND_LABEL[seatWind(seat.seat, dealer)]} wind"
			>{WIND_CHAR[seatWind(seat.seat, dealer)]}</span
		>
		{#if seat.seat === dealer}<span class="dealer-badge" title="Dealer">莊</span>{/if}
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
				aria-label={spectating ? `${seat.name}'s melds` : 'Your melds'}
			>
				{#if seat.flowers.length}
					<div class="meld" aria-label={spectating ? `${seat.name}'s flowers` : 'Your flowers'}>
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
			<div class="tile-row backs-row" aria-label="{seat.name}'s concealed hand">
				{#each seat.concealedHand ?? [] as code, i (i)}
					<div class="mini-tile"><TileFace {code} /></div>
				{/each}
			</div>
		{:else if spectating}
			<div class="tile-row backs-row" aria-label="{seat.concealedCount} concealed tiles">
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
			</div>
		{:else}
			<div class="hand-row" aria-label="Your concealed hand">
				{#each ownHandTiles as tile (tile.key)}
					{#if !isMock && tile.tileId !== null && discardableTileIds.has(tile.tileId)}
						<button
							type="button"
							class="hand-tile hand-tile-btn"
							class:hand-tile--drawn={tile.drawn}
							aria-label="Discard {tile.code}"
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
			<div class="declare-actions" role="group" aria-label="Declare options">
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

	// fixed footprint (matches `TimerRing size={24}` above) so the header doesn't reflow --
	// `.seat-score`'s `margin-inline-start: auto` shifts position with any preceding sibling that
	// mounts/unmounts, and this one toggles every time the turn changes.
	.turn-timer {
		width: 24px;
		height: 24px;
		pointer-events: none;
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

	.seat-score {
		margin-inline-start: auto;
		font-variant-numeric: tabular-nums;
		color: var(--color-text-muted);
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

	// live-mode-only interactive hand tile: same box as the plain `.hand-tile` div (kept a button
	// only when there's a discard to send it) -- a button reset, not a second style.
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
			min-height: 44px;
			padding: var(--space-2) var(--space-3);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-primary;

			// `btn-primary`'s `:active` press (`translateY(3px)`) moves the button out from under a
			// held-then-released pointer before mouseup's hit-test runs, so mouseup/click lands on
			// this flex row's own `<div>` instead of the button -- Svelte's click delegation walks
			// up from the real event target and never reaches the button's handler, so the declare
			// action (win/kong) silently never sends. No visible-position feedback lost: `:hover`'s
			// background swap still shows the press.
			&:active:not(:disabled) {
				transform: none;
			}
		}
	}

	// sub-768px collapse (docs/03-frontend.md §3): pinned to the safe-area bottom, horizontal
	// scroll once a full hand no longer fits.
	@include layout.phone-only {
		.backs-row .mini-tile.back {
			margin-inline-end: -14px; // overlapping-backs strip, count-only

			&:last-child {
				margin-inline-end: 0;
			}
		}

		// `.table-tilt`'s `perspective` (unconditional, for the desktop rotateX, set in the parent
		// page) establishes a containing block for descendant `position: fixed` elements same as
		// `transform` does -- the parent page drops it at phone width too, so this pins to the
		// real viewport as intended, not the tilted box's own edge.
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

		// a full hand at this tile size is wider than a phone screen, and `.seat-region--self` is
		// `position: fixed` (no scrollable ancestor) -- without this, tiles past the edge are
		// simply unreachable rather than scrolled-to.
		.hand-row {
			overflow-x: auto;
		}
	}
</style>
