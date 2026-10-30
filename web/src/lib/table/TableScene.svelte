<script lang="ts">
	import type { Snippet } from 'svelte';
	import type { Seat } from '$lib/game/types';
	import type { DiscardMode } from '$lib/ui/client-prefs';
	import { m } from '$lib/paraglide/messages.js';
	import type { CoachTarget, DeclareOption, OwnHandTile, TableView } from './view-types';
	import { relativeSeat, seatAtPosition } from './wind';
	import OpponentRegion from './OpponentRegion.svelte';
	import CenterDiscardPool from './CenterDiscardPool.svelte';
	import YourSeatRegion from './YourSeatRegion.svelte';
	import SealStamp from './SealStamp.svelte';

	// props and callbacks only, no store or socket: renders a live table and a static snapshot alike.
	let {
		view,
		spectating,
		isMock,
		turn,
		hub,
		ownHandTiles,
		discardableTileIds,
		declareOptions,
		discardMode,
		onDiscard,
		arrangeable = false,
		onReorder = () => {},
		scoreDeltas = {},
		sealStamp = null,
		holdLastDiscard = false,
		coach = null
	}: {
		view: TableView;
		spectating: boolean;
		isMock: boolean;
		// the halo seat; -1 while a result overlay is up.
		turn: number;
		// rendered in the centre box; omitted when the page shows the hub in the header rail.
		hub?: Snippet;
		ownHandTiles: OwnHandTile[];
		discardableTileIds: Set<number>;
		declareOptions: DeclareOption[];
		discardMode: DiscardMode;
		onDiscard: (tileId: number) => void;
		arrangeable?: boolean;
		onReorder?: (tileId: number, toIndex: number) => void;
		scoreDeltas?: Record<number, { value: number; key: number }>;
		sealStamp?: { seat: number; glyph: string; key: number } | null;
		holdLastDiscard?: boolean;
		// the region a coach tip points at, outlined in brass.
		coach?: CoachTarget | null;
	} = $props();

	function seatAt(position: 0 | 1 | 2 | 3) {
		return seatAtPosition(view.seats, view.you, position);
	}

	function lastDiscardIndexFor(seat: Seat): number | null {
		const d = view.lastDiscard;
		return d && d.seat === seat ? d.index : null;
	}

	function scoreDeltaFor(seat: number): { value: number; key: number } | null {
		return scoreDeltas[seat] ?? null;
	}

	// table-relative side of the claimer: the badge sits just inside the centre box on that side.
	let sealStampPosition = $derived.by(() => {
		if (!sealStamp) return null;
		const sides = ['self', 'right', 'across', 'left'] as const;
		return sides[relativeSeat(sealStamp.seat as Seat, view.you)];
	});
</script>

<div class="table-surface" data-testid="table-scene" data-coach={coach ?? undefined}>
	<OpponentRegion
		seat={seatAt(2)}
		position="across"
		dealer={view.dealer as Seat}
		{turn}
		scoreDelta={scoreDeltaFor(seatAt(2).seat)}
	/>
	<OpponentRegion
		seat={seatAt(3)}
		position="left"
		dealer={view.dealer as Seat}
		{turn}
		scoreDelta={scoreDeltaFor(seatAt(3).seat)}
	/>
	<OpponentRegion
		seat={seatAt(1)}
		position="right"
		dealer={view.dealer as Seat}
		{turn}
		scoreDelta={scoreDeltaFor(seatAt(1).seat)}
	/>

	<div class="table-center">
		{@render hub?.()}
		<CenterDiscardPool
			seat={seatAt(2)}
			position="across"
			ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(2).name })}
			lastDiscardIndex={lastDiscardIndexFor(seatAt(2).seat)}
			{holdLastDiscard}
		/>
		<CenterDiscardPool
			seat={seatAt(3)}
			position="left"
			ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(3).name })}
			lastDiscardIndex={lastDiscardIndexFor(seatAt(3).seat)}
			{holdLastDiscard}
		/>
		<CenterDiscardPool
			seat={seatAt(1)}
			position="right"
			ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(1).name })}
			lastDiscardIndex={lastDiscardIndexFor(seatAt(1).seat)}
			{holdLastDiscard}
		/>
		<CenterDiscardPool
			seat={seatAt(0)}
			position="self"
			ariaLabel={spectating
				? m.tablePage_discardsAriaLabel({ name: seatAt(0).name })
				: m.tablePage_yourDiscardsAriaLabel()}
			lastDiscardIndex={lastDiscardIndexFor(seatAt(0).seat)}
			{holdLastDiscard}
		/>
		{#if sealStamp && sealStampPosition}
			{#key sealStamp.key}
				<SealStamp glyph={sealStamp.glyph} position={sealStampPosition} />
			{/key}
		{/if}
	</div>

	<YourSeatRegion
		seat={seatAt(0)}
		{spectating}
		dealer={view.dealer as Seat}
		{turn}
		{isMock}
		{ownHandTiles}
		{discardableTileIds}
		{discardMode}
		{onDiscard}
		{arrangeable}
		{onReorder}
		{declareOptions}
		scoreDelta={scoreDeltaFor(seatAt(0).seat)}
	/>
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.table-surface {
		@include layout.seat-region-grid;
		// tiles, pools and the hub size off the table's own width (cqi), not the viewport's:
		// the toolbar, page padding and rim make the two differ.
		container: table / inline-size;
		position: relative;
		height: 100%;
		min-height: 420px;
		padding: var(--space-3);
		// clip, not hidden: hidden makes this a scroll container, which traps the phone self
		// row's `position: sticky` inside the surface instead of the viewport.
		overflow: clip;
		// the top edge is TableToolbar's rail, same walnut, so the two read as one frame.
		border-radius: 0 0 var(--radius-lg) var(--radius-lg);
		// local override: --color-text-muted (walnut chrome) fails contrast on felt green;
		// every descendant using it (seat-wind, seat-score, …) gets the felt-safe value for free.
		--color-text-muted: var(--color-felt-muted);
		// walnut rim: a solid border plus an inner highlight ring (the lip catching light) and an
		// outer shadow (the rim sitting above the room, not flush with it).
		border: 10px solid var(--color-rim);
		border-top-width: 4px;
		box-shadow:
			inset 0 0 0 2px var(--color-rim-hi),
			0 10px 28px rgb(0 0 0 / 0.5);
		// felt: lit from above-centre, falling off to a deeper green at the rails.
		background: radial-gradient(
			ellipse 120% 85% at 50% 35%,
			var(--color-felt-lit),
			var(--color-felt) 55%,
			var(--color-felt-deep) 100%
		);
	}

	// static woven-felt grain (inline SVG feTurbulence, ~4% opacity), not a texture asset.
	// position: absolute keeps it out of the surface's own grid; pointer-events: none below it.
	.table-surface::before {
		content: '';
		position: absolute;
		inset: 0;
		pointer-events: none;
		opacity: 0.04;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
		background-size: 180px 180px;
	}

	// all four discard pools live in the centre, forming a box instead of each sitting at its own
	// seat's edge. below tablet-up the box dissolves: hub and pools become surface grid items.
	.table-center {
		grid-area: center;
		display: contents;

		@include layout.tablet-up {
			display: grid;
			align-items: center;
			grid-template-areas:
				'.    across .'
				'left hub    right'
				'.    self   .';
			grid-template-columns: clamp(26px, 4cqi, 36px) 1fr clamp(26px, 4cqi, 36px);
			grid-template-rows: clamp(26px, 4cqi, 36px) 1fr clamp(26px, 4cqi, 36px);
		}
	}

	// the compass hub owns the grid's centre cell; the pools form the box around it (frontend.md §2/§3).
	.table-center :global(.center-hub) {
		grid-area: center;
		align-self: center;

		@include layout.tablet-up {
			grid-area: hub;
			align-self: center;
			justify-self: center;
		}
	}

	// zone guide: a faint felt-line box around the discard area, reading as a dealt-in-the-centre
	// marking on the felt (like a real table's rail line), not a UI chrome border.
	.table-center {
		@include layout.tablet-up {
			outline: 1px solid var(--color-felt-line);
			outline-offset: var(--space-2);
			border-radius: var(--radius-sm);
		}
	}

	.table-center {
		@include layout.tablet-up {
			position: relative;
		}
	}

	.table-surface[data-coach='hand'] :global(.seat-region--self),
	.table-surface[data-coach='melds'] :global(.seat-region--self .meld-row),
	.table-surface[data-coach='discards'] .table-center,
	.table-surface[data-coach='wall'] :global(.wall-count),
	.table-surface[data-coach='hub'] :global(.center-hub) {
		outline: 2px solid var(--color-brass);
		outline-offset: 4px;
		border-radius: var(--radius-md);
	}

	@include layout.phone-only {
		.table-surface {
			flex: 1 0 auto;
			height: auto;
		}

		// .table-center has no box here, so the tip outlines each pool instead.
		.table-surface[data-coach='discards'] :global(.discard-pool) {
			outline: 2px solid var(--color-brass);
			outline-offset: 2px;
		}
	}

	@include layout.desktop-up {
		.table-surface {
			padding: var(--space-4);
		}
	}

	// a phone held sideways: no page scroll -- the surface takes what the toolbar leaves and
	// scrolls inside itself, the hand bar sticky at its bottom (layout.seat-region-grid).
	@include layout.phone-landscape {
		.table-surface {
			flex: 1 1 auto;
			height: 100%;
			min-height: 0;
			// no bottom padding: content scrolling under the sticky hand bar would show through it.
			padding: var(--space-1) var(--space-1) 0;
			border-width: 4px 6px 6px;
			overflow-y: auto;
			overscroll-behavior: contain;
		}
	}

	// portrait phone: rim and felt padding cost part of a 390px width; the hand gets it back.
	@include layout.phone-portrait {
		.table-surface {
			padding: var(--space-1);
			border-width: 4px 6px 6px;
		}
	}
</style>
