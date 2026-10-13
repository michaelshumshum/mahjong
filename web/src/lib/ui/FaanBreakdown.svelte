<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import { meldTileFace } from '../table/meld-face';
	import type { TileCode } from '../table/tile-code';
	import { m } from '$lib/paraglide/messages.js';
	import { faanPatternLabel } from './faan-pattern-labels';

	export type Seat = 0 | 1 | 2 | 3;

	// mirrors melds.MeldKind, minus PAIR -- kept local since this only needs kind/tiles.
	export type MeldKind = 'chow' | 'pung' | 'exposed_kong' | 'concealed_kong' | 'added_kong';

	export interface WinningMeld {
		kind: MeldKind;
		tiles: TileCode[];
	}

	export interface FaanPattern {
		name: string;
		faan: number;
	}

	// mirrors hand_end.payments: per-seat delta for this hand only. `Partial` because a seat
	// with nothing to pay or collect has no entry rather than an explicit 0.
	export type Payments = Partial<Record<Seat, number>>;

	const ALL_SEATS: Seat[] = [0, 1, 2, 3];

	let {
		winner,
		seatNames,
		winningHand,
		melds = [],
		patterns,
		totalFaan,
		payments
	}: {
		winner: Seat;
		// player names, not seat direction -- the win screen is about who won/lost.
		seatNames: Record<Seat, string>;
		winningHand: TileCode[];
		melds?: WinningMeld[];
		patterns: FaanPattern[];
		totalFaan: number;
		payments: Payments;
	} = $props();

	// reading order within a suit -- tiles arrive in claim/draw order, not sorted.
	const SUIT_ORDER: Record<string, number> = { m: 0, p: 1, s: 2 };
	function tileSortKey(code: TileCode): number {
		return code[0] === 'z'
			? 30 + Number(code[1])
			: (SUIT_ORDER[code[1]] ?? 9) * 9 + Number(code[0]);
	}
	function sortTiles(tiles: TileCode[]): TileCode[] {
		return tiles.slice().sort((a, b) => tileSortKey(a) - tileSortKey(b));
	}

	// melds themselves sorted by their first tile too, so a hand with several claimed sets reads
	// left-to-right in the same suit order as the concealed tiles beside them.
	let sortedMelds = $derived(
		melds
			.map((meld) => ({ ...meld, tiles: sortTiles(meld.tiles) }))
			.sort((a, b) => tileSortKey(a.tiles[0]) - tileSortKey(b.tiles[0]))
	);
	let sortedConcealedHand = $derived(sortTiles(winningHand));

	// reveal order for the staggered entrance: melds left to right, then the concealed hand.
	let meldOffsets = $derived(
		sortedMelds.reduce<number[]>(
			(acc, meld, i) => [...acc, i === 0 ? 0 : acc[i - 1] + sortedMelds[i - 1].tiles.length],
			[]
		)
	);
	let concealedOffset = $derived(sortedMelds.reduce((n, meld) => n + meld.tiles.length, 0));
	let tileCount = $derived(concealedOffset + sortedConcealedHand.length);

	// server clamps the total to faan_cap but still reports every pattern at full value --
	// comparing the raw pattern sum to totalFaan is enough to detect a capped hand.
	let patternSum = $derived(patterns.reduce((sum, p) => sum + p.faan, 0));
	let isCapped = $derived(patternSum > totalFaan);

	let seatPayments = $derived(
		ALL_SEATS.filter((seat) => !!payments[seat]).map((seat) => ({ seat, amount: payments[seat]! }))
	);
</script>

<section
	class="faan-breakdown"
	aria-labelledby="faan-breakdown-heading"
	style:--tile-count={tileCount}
	style:--pattern-count={patterns.length}
>
	<h2 id="faan-breakdown-heading">{m.faanBreakdown_winsHeading({ name: seatNames[winner] })}</h2>

	{#if sortedMelds.length > 0 || sortedConcealedHand.length > 0}
		<div class="winning-hand">
			{#if sortedMelds.length > 0}
				<div class="melds">
					{#each sortedMelds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (`${mi}:${ti}:${code}`)}
								<div class="tile" style:--i={meldOffsets[mi] + ti}>
									<TileFace code={meldTileFace(meld.kind, code, ti, meld.tiles.length)} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
			{#if sortedConcealedHand.length > 0}
				<div class="concealed-hand">
					{#each sortedConcealedHand as code, index (`${index}:${code}`)}
						<div class="tile" style:--i={concealedOffset + index}><TileFace {code} /></div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<ul class="patterns">
		{#each patterns as pattern, index (`${index}:${pattern.name}`)}
			<li class="pattern-row" style:--i={index}>
				<span class="pattern-name">{faanPatternLabel(pattern.name)}</span>
				<span class="pattern-faan">{m.faanBreakdown_faanCountLabel({ faan: pattern.faan })}</span>
			</li>
		{/each}
	</ul>

	<p class="total" class:total--capped={isCapped}>
		{m.faanBreakdown_totalLabel()}
		<strong>{m.faanBreakdown_faanCountLabel({ faan: totalFaan })}</strong>
		{#if isCapped}
			<span class="cap-note">{m.faanBreakdown_cappedFromLabel({ sum: patternSum })}</span>
		{/if}
	</p>

	<ul class="payments">
		{#each seatPayments as { seat, amount } (seat)}
			<li
				class="payment-row"
				class:payment-row--gain={amount > 0}
				class:payment-row--loss={amount < 0}
				class:payment-row--winner={seat === winner}
			>
				<span class="payment-seat">{seatNames[seat]}</span>
				<span class="payment-amount">{amount > 0 ? '+' : ''}{amount}</span>
			</li>
		{/each}
	</ul>
</section>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	// entrance choreography: tiles fan in one by one, then pattern rows, then total and payments.
	// delays are custom-property maths so the sequence scales with tile/pattern count.
	.faan-breakdown {
		--tile-step: 35ms;
		--row-step: 90ms;
		--tiles-done: calc(var(--dur-2) + var(--tile-count, 0) * var(--tile-step));
		--rows-done: calc(var(--tiles-done) + var(--pattern-count, 0) * var(--row-step));
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-xl);
		line-height: 1.1;
	}

	.winning-hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-3);
		border-radius: var(--radius-sm);
		background: var(--color-felt);
		box-shadow: inset 0 2px 6px rgb(0 0 0 / 0.35);
	}

	.melds,
	.concealed-hand {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.concealed-hand {
		gap: 2px;
	}

	.meld {
		display: flex;
		gap: 2px;
	}

	.tile :global(.tile-face) {
		height: clamp(40px, 9vw, 52px);
	}

	.tile {
		@include a11y.motion-ok {
			animation: tile-fan-in var(--dur-3) var(--ease-place) both;
			animation-delay: calc(var(--dur-2) + var(--i) * var(--tile-step));
		}
	}

	@keyframes tile-fan-in {
		from {
			opacity: 0;
			transform: translateY(-14px) rotate(-8deg) scale(0.9);
		}
	}

	.patterns {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.pattern-row {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		padding-block: 2px;
		border-bottom: 1px dashed color-mix(in srgb, var(--color-border) 70%, transparent);

		@include a11y.motion-ok {
			animation: row-in var(--dur-2) var(--ease-out) both;
			animation-delay: calc(var(--tiles-done) + var(--i) * var(--row-step));
		}
	}

	@keyframes row-in {
		from {
			opacity: 0;
			transform: translateX(-10px);
		}
	}

	.pattern-faan {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.total {
		margin: 0;
		font-size: var(--font-size-lg);
		font-variant-numeric: tabular-nums;

		@include a11y.motion-ok {
			animation: row-in var(--dur-2) var(--ease-out) both;
			animation-delay: var(--rows-done);
		}
	}

	// no accent here on purpose -- cinnabar is reserved for turn/claim-window/win-marker urgency.

	.cap-note {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.payments {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: var(--space-2);

		@include a11y.motion-ok {
			animation: row-in var(--dur-2) var(--ease-out) both;
			animation-delay: calc(var(--rows-done) + var(--dur-1));
		}
	}

	// name plate: player name on a raised chip, the delta as a tinted pill.
	.payment-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		min-width: 0;
		padding: var(--space-1) var(--space-1) var(--space-1) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		font-variant-numeric: tabular-nums;
	}

	.payment-row--winner {
		border-color: color-mix(in srgb, var(--color-brass) 70%, var(--color-border));
	}

	.payment-seat {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
		font-weight: 600;
	}

	.payment-amount {
		flex: none;
		padding: 2px var(--space-2);
		border-radius: 999px;
		font-weight: 700;
		background: rgb(255 255 255 / 0.06);
	}

	.payment-row--gain .payment-amount {
		color: var(--color-positive);
		background: color-mix(in srgb, var(--color-positive) 16%, transparent);
	}

	.payment-row--loss .payment-amount {
		color: var(--color-negative);
		background: color-mix(in srgb, var(--color-negative) 14%, transparent);
	}

	// phone landscape: the hand on the left, the scoring on the right, so payments sit above the
	// fold instead of under a full-width hand.
	@include layout.phone-landscape {
		.faan-breakdown {
			display: grid;
			grid-template-areas:
				'title title'
				'hand patterns'
				'hand total'
				'hand payments';
			grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr);
			align-content: start;
			align-items: start;
			gap: var(--space-2) var(--space-4);
		}

		h2 {
			grid-area: title;
			font-size: var(--font-size-lg);
		}

		.winning-hand {
			grid-area: hand;
			padding: var(--space-2);
		}

		.patterns {
			grid-area: patterns;
		}

		.total {
			grid-area: total;
			font-size: var(--font-size-base);
		}

		.payments {
			grid-area: payments;
		}

		.tile :global(.tile-face) {
			height: clamp(32px, 10dvh, 40px);
		}
	}
</style>
