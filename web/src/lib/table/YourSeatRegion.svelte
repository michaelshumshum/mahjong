<script lang="ts">
	import TileFace from './TileFace.svelte';
	import SeatPlate from './SeatPlate.svelte';
	import type { MockSeatState, Seat } from './mock-game-state';
	import type { TileCode } from './tile-code';
	import { tileName, tileOptionAriaLabel } from './tile-name';
	import TileOptionLabel from '$lib/ui/TileOptionLabel.svelte';
	import type { DiscardMode } from '$lib/ui/Settings.svelte';
	import { seatWind, windWord, WIND_CHAR } from './wind';
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
		declareOptions
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
	} = $props();

	// CenterHub carries the timer ring; this plain-text prompt is for your own seat, where a
	// ring alone (on a seat you're always looking at) is easy to miss.
	let isYourTurn = $derived(!spectating && seat.seat === turn && discardableTileIds.size > 0);

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

	function handleWindowKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape' && liftedTileId !== null) liftedTileId = null;
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
	/>

	<div class="your-hand">
		{#if isYourTurn || (isMock && seat.seat === turn && !spectating)}
			<p class="turn-prompt">{m.yourSeatRegion_yourTurnPrompt()}</p>
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
			<div
				class="hand-row"
				class:hand-row--two-step={discardMode === 'two-step'}
				aria-label={m.yourSeatRegion_yourConcealedHandAriaLabel()}
				bind:this={handRowEl}
			>
				{#each ownHandTiles as tile (tile.key)}
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

	// echoes SeatPlate's halo colour so the prompt reads as the same signal, not a second one.
	.turn-prompt {
		margin: 0;
		color: var(--color-accent);
		font-weight: 600;
		font-size: var(--font-size-sm);
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
		position: relative;
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;
		transition: transform var(--dur-1) var(--ease-out);
	}

	// lifted: translateY only (ADR 0002's transform/opacity rule), raised above its negative-
	// margin-overlapping neighbours so the full face stays visible even in phone overlap mode.
	.hand-tile-btn.hand-tile--lifted {
		z-index: 1;
		transform: translateY(-30%);
	}

	// desktop/fine-pointer preview only in two-step mode -- one-tap has no lift to preview.
	@media (hover: hover) and (pointer: fine) {
		.hand-row--two-step .hand-tile-btn:not(.hand-tile--lifted):hover {
			z-index: 1;
			transform: translateY(-12%);
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
		}
	}
</style>
