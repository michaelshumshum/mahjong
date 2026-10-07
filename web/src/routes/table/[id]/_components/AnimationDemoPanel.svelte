<script lang="ts">
	// sandbox proving the positional slot-identity mechanics (tile-slots.ts) and the transform/
	// opacity-only transition contract work end to end. No JS ticker -- `ontransitionend` commits the change.
	import ModalDialog from '$lib/ui/ModalDialog.svelte';
	import TileFace from '$lib/table/TileFace.svelte';
	import SeatPlate from '$lib/table/SeatPlate.svelte';
	import SealStamp from '$lib/table/SealStamp.svelte';
	import type { MeldKind, MockMeld } from '$lib/table/mock-game-state';
	import type { TileCode } from '$lib/table/tile-code';
	import {
		initialSlotState,
		popSlotForDiscard,
		popSlotsForConcealedKong,
		pushDrawnSlot,
		type SlotState
	} from '$lib/table/tile-slots';
	import CloseButton from '$lib/ui/CloseButton.svelte';
	import { m } from '$lib/paraglide/messages.js';

	let { onClose }: { onClose: () => void } = $props();

	const DEMO_REVEAL_POOL: TileCode[] = ['5s', '3p', '7m', 'z1', '9p', 'z5', '4s', '2m'];
	let demoRevealIndex = $state(0);
	function nextRevealedTile(): TileCode {
		const code = DEMO_REVEAL_POOL[demoRevealIndex % DEMO_REVEAL_POOL.length];
		demoRevealIndex += 1;
		return code;
	}

	let demoOpponentSlots: SlotState = $state(initialSlotState(13));
	let demoOpponentDiscards: TileCode[] = $state([]);
	let demoOpponentMelds: MockMeld[] = $state([]);
	let leavingOpponentSlotKey: number | null = $state(null);
	let leavingOpponentTile: TileCode | null = $state(null);

	// same element (keyed by slot.key) throughout back -> revealed-and-leaving -> gone --
	// appending the departed slot back rather than letting it disappear from the each-block early.
	let renderedOpponentSlots = $derived(
		leavingOpponentSlotKey !== null
			? [...demoOpponentSlots.slots, { key: leavingOpponentSlotKey }]
			: demoOpponentSlots.slots
	);

	function demoOpponentDraw(): void {
		demoOpponentSlots = pushDrawnSlot(demoOpponentSlots);
	}

	function demoOpponentDiscard(): void {
		if (leavingOpponentSlotKey !== null) return; // one flight at a time
		if (demoOpponentSlots.slots.length === 0) return;
		const { left, remaining } = popSlotForDiscard(demoOpponentSlots);
		leavingOpponentTile = nextRevealedTile(); // morphs face-up immediately (§4)
		leavingOpponentSlotKey = left.key;
		demoOpponentSlots = remaining;
	}

	function commitOpponentDiscard(): void {
		if (leavingOpponentSlotKey === null || leavingOpponentTile === null) return;
		demoOpponentDiscards = [...demoOpponentDiscards, leavingOpponentTile];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
	}

	function demoOpponentConcealedKong(): void {
		if (demoOpponentSlots.slots.length < 4) return;
		const { remaining } = popSlotsForConcealedKong(demoOpponentSlots);
		demoOpponentSlots = remaining;
		// morphs in place -- no flight, the tiles never leave the seat (§4).
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'concealed_kong', tiles: ['1m', '1m', '1m', '1m'] }
		];
	}

	function demoOpponentClaim(): void {
		// last discarded tile claimed into an exposed pung -- the discard-pool -> meld flight
		// path, independent of the concealed-slot logic above (this tile is already revealed).
		if (demoOpponentDiscards.length === 0) return;
		const claimed = demoOpponentDiscards[demoOpponentDiscards.length - 1];
		demoOpponentDiscards = demoOpponentDiscards.slice(0, -1);
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'pung', tiles: [claimed, claimed, claimed], fromSeat: 0 }
		];
	}

	interface DemoTile {
		id: number;
		code: TileCode;
	}
	let demoTileIdSeed = 0;
	function demoTile(code: TileCode): DemoTile {
		demoTileIdSeed += 1;
		return { id: demoTileIdSeed, code };
	}
	let demoYourHand: DemoTile[] = $state([
		demoTile('1m'),
		demoTile('9s'),
		demoTile('z5'),
		demoTile('3p'),
		demoTile('7m')
	]);
	let demoYourDiscards: DemoTile[] = $state([]);
	let leavingYourTileId: number | null = $state(null);

	function demoYourDiscard(id: number): void {
		if (leavingYourTileId !== null) return;
		leavingYourTileId = id;
	}

	function commitYourDiscard(): void {
		if (leavingYourTileId === null) return;
		const tile = demoYourHand.find((t) => t.id === leavingYourTileId);
		demoYourHand = demoYourHand.filter((t) => t.id !== leavingYourTileId);
		if (tile) demoYourDiscards = [...demoYourDiscards, tile];
		leavingYourTileId = null;
	}

	// SealStamp and SeatPlate's scoreDelta are transient signals -- previewed here on real
	// instances since the frozen mock scenarios never produce the transition that triggers them.
	const SEAL_GLYPH: Record<MeldKind, string> = {
		chow: '上',
		pung: '碰',
		exposed_kong: '槓',
		concealed_kong: '槓',
		added_kong: '槓'
	};
	let demoSealSeq = 0;
	let demoSealStamp: { glyph: string; key: number } | null = $state(null);
	function triggerDemoSeal(kind: MeldKind): void {
		demoSealSeq += 1;
		demoSealStamp = { glyph: SEAL_GLYPH[kind], key: demoSealSeq };
	}

	let demoScoreDeltaSeq = 0;
	let demoScoreDelta: { value: number; key: number } | null = $state(null);
	function triggerDemoScoreDelta(value: number): void {
		demoScoreDeltaSeq += 1;
		demoScoreDelta = { value, key: demoScoreDeltaSeq };
	}

	function resetAnimationDemo(): void {
		demoOpponentSlots = initialSlotState(13);
		demoOpponentDiscards = [];
		demoOpponentMelds = [];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
		demoYourHand = [demoTile('1m'), demoTile('9s'), demoTile('z5'), demoTile('3p'), demoTile('7m')];
		demoYourDiscards = [];
		leavingYourTileId = null;
		demoSealStamp = null;
		demoScoreDelta = null;
	}
</script>

<ModalDialog testid="animation-demo" label={m.animationDemoPanel_heading()} onCancel={onClose}>
	<div class="animation-demo">
		<CloseButton onclick={onClose} />
		<h2>{m.animationDemoPanel_heading()}</h2>
		<p class="demo-hint">
			{m.animationDemoPanel_hint()}
		</p>

		<section aria-label={m.animationDemoPanel_sealStampSectionAriaLabel()}>
			<h3>{m.animationDemoPanel_sealStampHeading()}</h3>
			<div class="demo-seat-plate-preview">
				<SeatPlate
					name={m.animationDemoPanel_youHeading()}
					windChar="東"
					windAriaLabel={m.animationDemoPanel_youHeading()}
					isDealer={false}
					dealerTitle=""
					score={0}
					scoreDelta={demoScoreDelta}
				/>
				{#if demoSealStamp}
					{#key demoSealStamp.key}
						<SealStamp glyph={demoSealStamp.glyph} />
					{/key}
				{/if}
			</div>
			<div class="demo-actions">
				<button type="button" onclick={() => triggerDemoSeal('chow')}
					>{m.animationDemoPanel_sealChowButton()}</button
				>
				<button type="button" onclick={() => triggerDemoSeal('pung')}
					>{m.animationDemoPanel_sealPungButton()}</button
				>
				<button type="button" onclick={() => triggerDemoSeal('exposed_kong')}
					>{m.animationDemoPanel_sealKongButton()}</button
				>
				<button type="button" onclick={() => triggerDemoScoreDelta(24)}
					>{m.animationDemoPanel_scoreDeltaPositiveButton()}</button
				>
				<button type="button" onclick={() => triggerDemoScoreDelta(-16)}
					>{m.animationDemoPanel_scoreDeltaNegativeButton()}</button
				>
			</div>
		</section>

		<section aria-label={m.animationDemoPanel_opponentSeatAriaLabel()}>
			<h3>{m.animationDemoPanel_opponentHeading()}</h3>
			<div
				class="tile-row backs-row"
				aria-label={m.animationDemoPanel_opponentConcealedAriaLabel()}
			>
				{#each renderedOpponentSlots as slot (slot.key)}
					<div
						class="mini-tile back demo-slot"
						class:demo-tile-leaving={slot.key === leavingOpponentSlotKey}
						ontransitionend={slot.key === leavingOpponentSlotKey
							? commitOpponentDiscard
							: undefined}
					>
						<TileFace code={slot.key === leavingOpponentSlotKey ? leavingOpponentTile : null} />
					</div>
				{/each}
			</div>
			{#if demoOpponentMelds.length}
				<div class="tile-row meld-row" aria-label={m.animationDemoPanel_opponentMeldsAriaLabel()}>
					{#each demoOpponentMelds as meld, mi (mi)}
						<div class="meld demo-meld-entering">
							{#each meld.tiles as code, ti (ti)}
								<div class="mini-tile">
									<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
			<div
				class="discard-pool"
				role="list"
				aria-label={m.animationDemoPanel_opponentDiscardsAriaLabel()}
			>
				{#each demoOpponentDiscards as code, i (i)}
					<div class="discard-tile" role="listitem"><TileFace {code} /></div>
				{/each}
			</div>
			<div class="demo-actions">
				<button type="button" onclick={demoOpponentDraw}>{m.animationDemoPanel_drawButton()}</button
				>
				<button
					type="button"
					onclick={demoOpponentDiscard}
					disabled={leavingOpponentSlotKey !== null || demoOpponentSlots.slots.length === 0}
				>
					{m.animationDemoPanel_discardButton()}
				</button>
				<button
					type="button"
					onclick={demoOpponentConcealedKong}
					disabled={demoOpponentSlots.slots.length < 4}
				>
					{m.animationDemoPanel_concealedKongButton()}
				</button>
				<button
					type="button"
					onclick={demoOpponentClaim}
					disabled={demoOpponentDiscards.length === 0}
				>
					{m.animationDemoPanel_claimLastDiscardButton()}
				</button>
			</div>
		</section>

		<section aria-label={m.animationDemoPanel_yourSeatAriaLabel()}>
			<h3>{m.animationDemoPanel_youHeading()}</h3>
			<div
				class="hand-row"
				aria-label={m.animationDemoPanel_yourHandAriaLabel()}
				data-testid="demo-your-hand"
			>
				{#each demoYourHand as tile (tile.id)}
					<button
						type="button"
						class="hand-tile demo-hand-tile"
						class:demo-tile-leaving={tile.id === leavingYourTileId}
						disabled={leavingYourTileId !== null}
						aria-label={m.animationDemoPanel_discardTileAriaLabel({ tile: tile.code })}
						onclick={() => demoYourDiscard(tile.id)}
						ontransitionend={tile.id === leavingYourTileId ? commitYourDiscard : undefined}
					>
						<TileFace code={tile.code} />
					</button>
				{/each}
			</div>
			<div
				class="discard-pool discard-pool--self"
				role="list"
				aria-label={m.animationDemoPanel_yourDiscardsAriaLabel()}
				data-testid="demo-your-discards"
			>
				{#each demoYourDiscards as tile (tile.id)}
					<div class="discard-tile" role="listitem"><TileFace code={tile.code} /></div>
				{/each}
			</div>
		</section>

		<button type="button" class="demo-reset" onclick={resetAnimationDemo}
			>{m.animationDemoPanel_resetButton()}</button
		>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';
	@use '$lib/styles/tile';

	// this sandbox can't share OpponentRegion/YourSeatRegion's scoped selectors directly, but
	// the shape of each rule is identical, so it goes through the same _tile.scss mixins.
	.tile-row {
		@include tile.tile-row;
	}

	.mini-tile {
		@include tile.mini-tile;
	}

	.meld {
		@include tile.meld;
	}

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 28px));
		justify-content: start;
		gap: 2px;
		max-width: 14rem;
	}

	.discard-tile {
		@include tile.mini-tile(clamp(22px, 3.5vw, 32px));
	}

	.hand-row {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}

	.hand-tile {
		@include tile.mini-tile;
	}

	.animation-demo {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 32rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	// SeatPlate's score-delta overlay is absolutely positioned on the plate -- give the preview a
	// sized, positioned box to anchor against, same as a real seat region.
	.demo-seat-plate-preview {
		gap: var(--space-3);
		align-items: center;
		position: relative;
		display: inline-flex;
		padding: var(--space-2) var(--space-4);
		background: var(--color-surface);
		border-radius: var(--radius-md);
	}

	.demo-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.demo-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.demo-actions button,
	.demo-reset {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.demo-hand-tile {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;

		&:disabled {
			cursor: not-allowed;
		}
	}

	// transform+opacity only -- no layout-affecting property, so this never triggers reflow.
	.demo-tile-leaving {
		transition:
			transform 260ms ease-in,
			opacity 260ms ease-in;
		transform: translateY(24px) scale(0.85);
		opacity: 0;
	}

	// a claimed/kong meld is a freshly-inserted DOM node, so this animation plays automatically
	// on insert with no JS trigger needed at all.
	.demo-meld-entering {
		animation: demo-meld-in 220ms ease-out;
	}

	@keyframes demo-meld-in {
		from {
			opacity: 0;
			transform: translateY(-10px) scale(0.9);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}

	// keep a near-instant transition running -- `transition: none` would leave the demo stuck
	// mid-flight, since ontransitionend is what commits the data change.
	.demo-tile-leaving {
		@include a11y.motion-reduced {
			transition-duration: 1ms;
			transform: none;
		}
	}

	.demo-meld-entering {
		@include a11y.motion-reduced {
			animation-duration: 1ms;
		}
	}
</style>
