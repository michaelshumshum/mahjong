<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
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

	// server clamps the total to faan_cap but still reports every pattern at full value --
	// comparing the raw pattern sum to totalFaan is enough to detect a capped hand.
	let patternSum = $derived(patterns.reduce((sum, p) => sum + p.faan, 0));
	let isCapped = $derived(patternSum > totalFaan);

	let seatPayments = $derived(
		ALL_SEATS.filter((seat) => !!payments[seat]).map((seat) => ({ seat, amount: payments[seat]! }))
	);
</script>

<section class="faan-breakdown" aria-labelledby="faan-breakdown-heading">
	<h2 id="faan-breakdown-heading">{m.faanBreakdown_winsHeading({ name: seatNames[winner] })}</h2>

	{#if sortedMelds.length > 0 || sortedConcealedHand.length > 0}
		<div class="winning-hand">
			{#if sortedMelds.length > 0}
				<div class="melds">
					{#each sortedMelds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (`${mi}:${ti}:${code}`)}
								<div class="tile">
									<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
			{#if sortedConcealedHand.length > 0}
				<div class="concealed-hand">
					{#each sortedConcealedHand as code, index (`${index}:${code}`)}
						<div class="tile"><TileFace {code} /></div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<ul class="patterns">
		{#each patterns as pattern, index (`${index}:${pattern.name}`)}
			<li class="pattern-row">
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
			>
				<span class="payment-seat">{seatNames[seat]}</span>
				<span class="payment-amount">{amount > 0 ? '+' : ''}{amount}</span>
			</li>
		{/each}
	</ul>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.faan-breakdown {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 24rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.winning-hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.melds,
	.concealed-hand {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.meld {
		display: flex;
		gap: 2px;
	}

	.tile :global(.tile-face) {
		height: 48px;
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
	}

	.pattern-faan {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.total {
		margin: 0;
		padding-block-start: var(--space-2);
		border-top: 1px solid var(--color-border);
		font-size: var(--font-size-lg);
		font-variant-numeric: tabular-nums;
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
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.payment-row {
		display: flex;
		justify-content: space-between;
		gap: var(--space-3);
		font-variant-numeric: tabular-nums;
	}

	.payment-row--gain .payment-amount {
		color: var(--color-positive);
	}

	.payment-row--loss .payment-amount {
		color: var(--color-negative);
	}
</style>
