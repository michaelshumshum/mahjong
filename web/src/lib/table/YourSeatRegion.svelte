<script lang="ts">
	import { flip } from 'svelte/animate';
	import TileFace from './TileFace.svelte';
	import SeatPlate from './SeatPlate.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import type { TileCode } from './tile-code';
	import { tileName, tileOptionAriaLabel } from './tile-name';
	import TileOptionLabel from '$lib/ui/TileOptionLabel.svelte';
	import type { DiscardMode } from '$lib/ui/Settings.svelte';
	import { seatWind, windWord, WIND_CHAR } from './wind';
	import { motionMs } from '$lib/ui/motion';
	import { m } from '$lib/paraglide/messages.js';

	// how long a sent discard waits for the server echo before a stalled indicator (§5) --
	// cosmetic, resolved by the normal reconnect/resync path, never a client-side guess.
	const PENDING_STALL_MS = 3000;

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
		// a self-drawn win: the one declare option worth making unmissable (P1.10) -- kongs stay
		// secondary buttons alongside it, never competing for the eye.
		hero?: boolean;
	}

	let {
		seat,
		spectating,
		dealer,
		turn,
		isMock,
		ownHandTiles,
		discardableTileIds,
		discardMode,
		onDiscard,
		declareOptions,
		scoreDelta = null
	}: {
		seat: MockSeatState;
		spectating: boolean;
		dealer: Seat;
		turn: number;
		isMock: boolean;
		ownHandTiles: OwnHandTile[];
		discardableTileIds: Set<number>;
		discardMode: DiscardMode;
		onDiscard: (tileId: number) => void;
		declareOptions: DeclareOption[];
		scoreDelta?: { value: number; key: number } | null;
	} = $props();

	// two-step: the lifted tile is presentation-only state, never game truth. A second tap/Enter
	// on it (same button, same onclick) discards; another tile moves the lift; outside-click/Esc clears it.
	let liftedTileId = $state<number | null>(null);
	let handRowEl: HTMLDivElement | null = $state(null);

	// pending: dims the tile with a spinner until the echo removes it from `ownHandTiles` (or the
	// turn/hand moves on) -- presentation only, never reverted (a legal discard can't be rejected).
	let pendingTileId = $state<number | null>(null);
	let pendingStalled = $state(false);
	let pendingTimer: ReturnType<typeof setTimeout> | null = null;

	function clearPending(): void {
		pendingTileId = null;
		pendingStalled = false;
		if (pendingTimer !== null) {
			clearTimeout(pendingTimer);
			pendingTimer = null;
		}
	}

	function performDiscard(tileId: number): void {
		liftedTileId = null;
		pendingTileId = tileId;
		pendingStalled = false;
		if (pendingTimer !== null) clearTimeout(pendingTimer);
		pendingTimer = setTimeout(() => {
			pendingStalled = true;
		}, PENDING_STALL_MS);
		onDiscard(tileId);
	}

	function handleTileActivate(tileId: number): void {
		if (discardMode === 'one-tap' || liftedTileId === tileId) {
			performDiscard(tileId);
		} else {
			liftedTileId = tileId;
		}
	}

	// clears a lift once the echo (or a turn/hand change) actually lands -- never a client guess
	// at the outcome, just noticing the tile is no longer ours to discard.
	$effect(() => {
		if (pendingTileId === null) return;
		const stillPending = seat.seat === turn && ownHandTiles.some((t) => t.tileId === pendingTileId);
		if (!stillPending) clearPending();
	});

	$effect(() => {
		return () => {
			if (pendingTimer !== null) clearTimeout(pendingTimer);
		};
	});

	function handleWindowClick(e: MouseEvent): void {
		if (liftedTileId === null) return;
		if (handRowEl && !handRowEl.contains(e.target as Node)) liftedTileId = null;
	}

	// roving tabindex (frontend.md §9): the hand is one tab stop; arrows/Home/End move focus
	// between discardable tiles, Enter/Space go through the same onclick as a tap.
	let focusedTileId = $state<number | null>(null);
	const discardableOrder = $derived(
		isMock
			? []
			: ownHandTiles
					.map((t) => t.tileId)
					.filter((id): id is number => id !== null && discardableTileIds.has(id))
	);
	// defaults to the last discardable tile: the drawn tile, held out at the right.
	const rovingTileId = $derived.by(() => {
		for (const id of [focusedTileId, liftedTileId]) {
			if (id !== null && discardableOrder.includes(id)) return id;
		}
		return discardableOrder.at(-1) ?? null;
	});

	function focusTile(tileId: number): void {
		focusedTileId = tileId;
		handRowEl?.querySelector<HTMLElement>(`[data-tile-id="${tileId}"]`)?.focus();
	}

	function handleHandKeydown(e: KeyboardEvent): void {
		if (rovingTileId === null) return;
		const last = discardableOrder.length - 1;
		const index = discardableOrder.indexOf(rovingTileId);
		let next: number;
		if (e.key === 'ArrowRight') next = Math.min(index + 1, last);
		else if (e.key === 'ArrowLeft') next = Math.max(index - 1, 0);
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = last;
		else return;
		e.preventDefault();
		focusTile(discardableOrder[next]);
	}

	function isTypingTarget(target: EventTarget | null): boolean {
		return (
			target instanceof HTMLElement &&
			(target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))
		);
	}

	function handleWindowKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && liftedTileId !== null) liftedTileId = null;
		const jump = e.key === 'h' || e.key === 'H';
		if (!jump || e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
		if (!handRowEl) return;
		e.preventDefault();
		// not your turn: no tile is focusable, so the row itself takes focus (tabindex -1).
		if (rovingTileId !== null) focusTile(rovingTileId);
		else handRowEl.focus();
	}
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleWindowKeydown} />

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

	<SeatPlate
		name={seat.name}
		windChar={WIND_CHAR[seatWind(seat.seat, dealer)]}
		windAriaLabel={m.yourSeatRegion_windAriaLabel({ wind: windWord(seatWind(seat.seat, dealer)) })}
		isDealer={seat.seat === dealer}
		dealerTitle={m.yourSeatRegion_dealerBadgeTitle()}
		score={seat.score}
		isTurn={seat.seat === turn}
		{scoreDelta}
	/>

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
			<div
				class="hand-row"
				role="toolbar"
				tabindex="-1"
				aria-label={m.yourSeatRegion_yourConcealedHandAriaLabel()}
				aria-keyshortcuts="h"
				bind:this={handRowEl}
				onkeydown={handleHandKeydown}
			>
				{#each ownHandTiles as tile (tile.key)}
					<div
						class="hand-tile-slot"
						class:hand-tile-slot--drawn={tile.drawn}
						animate:flip={{ duration: motionMs(220) }}
					>
						{#if !isMock && tile.tileId !== null && discardableTileIds.has(tile.tileId)}
							{@const lifted = liftedTileId === tile.tileId}
							{@const pending = pendingTileId === tile.tileId}
							<button
								type="button"
								class="hand-tile hand-tile-btn"
								class:hand-tile--drawn={tile.drawn}
								class:hand-tile--lifted={lifted}
								class:hand-tile--pending={pending}
								disabled={pending}
								data-tile-id={tile.tileId}
								tabindex={rovingTileId === tile.tileId ? 0 : -1}
								onfocus={() => (focusedTileId = tile.tileId)}
								aria-label={m.yourSeatRegion_discardTileAriaLabel({ tile: tileName(tile.code) })}
								onclick={() => handleTileActivate(tile.tileId as number)}
							>
								<TileFace code={tile.code} />
								{#if pending}
									<span
										class="pending-spinner"
										class:pending-spinner--stalled={pendingStalled}
										aria-hidden="true"
									></span>
								{/if}
							</button>
						{:else}
							<div class="hand-tile" class:hand-tile--drawn={tile.drawn}>
								<TileFace code={tile.code} />
							</div>
						{/if}
					</div>
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
						class="declare-btn"
						class:declare-btn--hero={opt.hero}
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

	// the flip-animated flex item -- the inner button/div just fills it. animate: needs the
	// each-block's sole child, so the slot, not the tile itself, carries it.
	.hand-tile-slot {
		flex: none;
		width: var(--hand-tile-w);
		height: calc(var(--hand-tile-w) * 4 / 3);
	}

	.hand-tile-slot + .hand-tile-slot {
		margin-inline-start: var(--hand-step);
	}

	.hand-row .hand-tile-slot--drawn {
		margin-inline-start: calc(var(--hand-drawn-gap) + var(--hand-step));
	}

	.hand-tile {
		display: block;
		width: 100%;
		height: 100%;
	}

	.hand-tile :global(.tile-face) {
		height: 100%;
	}

	// same box as the plain .hand-tile div -- a button reset, not a second style.
	.hand-tile-btn {
		position: relative;
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;
		transition: transform var(--dur-1) var(--ease-out);
		// rapid taps on ios otherwise select the face glyph or flash the grey tap highlight.
		-webkit-tap-highlight-color: transparent;
		-webkit-touch-callout: none;
		user-select: none;

		// hit area extended down by the lift so the pointer stays over a raised tile; without it,
		// hovering the bottom edge lifts the tile off the pointer and hover/cursor flicker.
		&::after {
			content: '';
			position: absolute;
			inset: 0;
		}
	}

	// lifted: translateY only (ADR 0002's transform/opacity rule), raised above its negative-
	// margin-overlapping neighbours so the full face stays visible even in phone overlap mode.
	.hand-tile-btn.hand-tile--lifted {
		z-index: 1;
		transform: translateY(-30%);

		&::after {
			bottom: -30%;
		}
	}

	// desktop/fine-pointer hover preview, both discard modes.
	@media (hover: hover) and (pointer: fine) {
		.hand-tile-btn:not(.hand-tile--lifted):not(:disabled):hover {
			z-index: 1;
			transform: translateY(-12%);

			&::after {
				bottom: -12%;
			}
		}
	}

	.hand-tile--pending {
		cursor: default;

		:global(.tile-face) {
			opacity: 0.45;
		}
	}

	.pending-spinner {
		position: absolute;
		top: 2px;
		right: 2px;
		width: 0.85rem;
		height: 0.85rem;
		border: 2px solid var(--color-border);
		border-top-color: var(--color-text);
		border-radius: 50%;
		// a functional in-progress indicator, not decorative -- spins regardless of the reduced-
		// motion setting (frontend.md §9's exception list: seat-slot breathing, spinners, …).
		animation: pending-spin 700ms linear infinite;
	}

	// after PENDING_STALL_MS with no server echo: a steady accent ring instead of a spin, since
	// the resync path (not a client guess) resolves what actually happened.
	.pending-spinner--stalled {
		border-color: var(--color-status-error);
		border-top-color: var(--color-status-error);
		animation: none;
	}

	@keyframes pending-spin {
		to {
			transform: rotate(360deg);
		}
	}

	.declare-actions {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}

	// kongs are secondary: real but unhurried, never competing with a self-drawn win for the eye.
	.declare-btn {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;

		// the hero variant below uses btn-primary's :active translateY(3px), which moves the
		// button out from under mouseup's hit-test so the click lands on the row's div instead.
		&:active:not(:disabled) {
			transform: none;
		}
	}

	// P1.10: a self-drawn win is the one declare option worth making unmissable -- bigger, the
	// accent hero treatment, not just another same-sized button in the row.
	.declare-btn--hero {
		padding: var(--space-3) var(--space-5);
		font-size: var(--font-size-lg);
		@include buttons.btn-primary;

		&:active:not(:disabled) {
			transform: none;
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
			row-gap: 0;
		}

		// the hand sits flush under the plate; a lifted tile (z-index 1) overlaps the plate.
		.meld-row {
			margin-block-end: var(--space-2);
		}
	}

	// portrait phone: 14 tiles in one row overlap to ~half a face, so wrap to rows of 8 that
	// never overlap; the centre has height to spare.
	@include layout.phone-portrait {
		.seat-region--self {
			padding-inline: var(--space-1);
		}

		.hand-row {
			--hand-tile-w: clamp(
				36px,
				calc((100cqi - 7 * var(--hand-gap) - var(--hand-drawn-gap) - 1px) / 8),
				63px
			);
			--hand-step: var(--hand-gap);
			flex-wrap: wrap;
			row-gap: var(--hand-gap);
		}

		.hand-tile-slot:nth-child(8n + 1):not(.hand-tile-slot--drawn) {
			margin-inline-start: 0;
		}

		// rows sit 2px apart, so a lifted tile overlaps the row above: only its own slot takes the
		// tap, or a tap on the tile behind it would discard the lifted one.
		.hand-tile-btn.hand-tile--lifted {
			pointer-events: none;

			&::after {
				top: 30%;
				pointer-events: auto;
			}
		}
	}

	// short landscape: melds share the plate's row instead of taking their own, and tiles grow
	// with width only as far as ~16% of the viewport height allows (44px floor, 56px cap).
	@include layout.phone-landscape {
		.seat-region--self {
			display: grid;
			grid-template-areas: 'plate melds' 'hand hand';
			grid-template-columns: auto minmax(0, 1fr);
			align-items: end;
			column-gap: var(--space-4);
		}

		.seat-region--self > :global(.seat-plate) {
			grid-area: plate;
		}

		.meld-row {
			grid-area: melds;
			min-block-size: 0;
			margin-block-end: 0;
		}

		.your-hand {
			grid-area: hand;
		}

		.hand-row {
			--hand-tile-w: clamp(44px, min(var(--hand-fit-w), 16dvh * 3 / 4), 56px);
		}
	}
</style>
