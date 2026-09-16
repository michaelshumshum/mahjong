<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import type { TileCode } from '../table/tile-code';

	export type Seat = 0 | 1 | 2 | 3;

	export interface FaanPattern {
		name: string;
		faan: number;
	}

	// mirrors hand_end.payments (docs/02-protocol.md §3): per-seat point delta for *this hand*
	// only, not the running game total (`score.totals` — the score sheet's job, a separate
	// component). Winner positive, payer(s) negative, entries sum to zero. `Partial` because a
	// seat with nothing to pay or collect (e.g. a non-discarder under `discarder_pays_all`)
	// simply has no entry rather than an explicit 0.
	export type Payments = Partial<Record<Seat, number>>;

	const SEAT_LABEL: Record<Seat, string> = { 0: 'East', 1: 'South', 2: 'West', 3: 'North' };
	const ALL_SEATS: Seat[] = [0, 1, 2, 3];

	let {
		winner,
		winningHand,
		patterns,
		totalFaan,
		payments
	}: {
		winner: Seat;
		winningHand: TileCode[];
		patterns: FaanPattern[];
		totalFaan: number;
		payments: Payments;
	} = $props();

	// docs/01-rules-spec.md §7 clamps the total to `RuleSet.faan_cap` server-side ("Total is
	// clamped") but still reports every matched pattern at its full value — comparing the raw
	// pattern sum to the given `totalFaan` is enough to detect and label a capped hand without
	// this component needing its own copy of the ruleset. Not in the protocol doc's sketch (it
	// only names the `faan_breakdown` key, not its shape) — this is the shape decision this
	// component's props codify.
	let patternSum = $derived(patterns.reduce((sum, p) => sum + p.faan, 0));
	let isCapped = $derived(patternSum > totalFaan);

	let seatPayments = $derived(
		ALL_SEATS.filter((seat) => !!payments[seat]).map((seat) => ({ seat, amount: payments[seat]! }))
	);
</script>

<section class="faan-breakdown" aria-labelledby="faan-breakdown-heading">
	<h2 id="faan-breakdown-heading">{SEAT_LABEL[winner]} wins</h2>

	{#if winningHand.length > 0}
		<div class="winning-hand">
			{#each winningHand as code, index (`${index}:${code}`)}
				<div class="tile"><TileFace {code} /></div>
			{/each}
		</div>
	{/if}

	<ul class="patterns">
		{#each patterns as pattern, index (`${index}:${pattern.name}`)}
			<li class="pattern-row">
				<span class="pattern-name">{pattern.name}</span>
				<span class="pattern-faan">{pattern.faan} faan</span>
			</li>
		{/each}
	</ul>

	<p class="total" class:total--capped={isCapped}>
		Total <strong>{totalFaan} faan</strong>
		{#if isCapped}
			<span class="cap-note">(capped from {patternSum})</span>
		{/if}
	</p>

	<ul class="payments">
		{#each seatPayments as { seat, amount } (seat)}
			<li
				class="payment-row"
				class:payment-row--gain={amount > 0}
				class:payment-row--loss={amount < 0}
			>
				<span class="payment-seat">{SEAT_LABEL[seat]}</span>
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
		flex-wrap: wrap;
		gap: var(--space-1);
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

	// no accent here on purpose — cinnabar is reserved for turn/claim-window/win-marker urgency
	// (docs this sub-task follows), not a "notable number" highlight. The cap-note text alone
	// carries the information.

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
		color: var(--color-accent-jade);
	}

	.payment-row--loss .payment-amount {
		color: var(--color-accent);
	}
</style>
