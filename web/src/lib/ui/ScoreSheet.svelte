<script lang="ts">
	import type { Seat } from './FaanBreakdown.svelte';

	export type Wind = 'E' | 'S' | 'W' | 'N';

	export interface SeatInfo {
		seat: Seat;
		name: string;
	}

	// mirrors score.totals (docs/02-protocol.md §3): the authoritative running total per seat, as
	// last received from the server. Kept as its own prop rather than derived only from `hands`
	// below — see `historyComplete`.
	export type Totals = Record<Seat, number>;

	// mirrors hand_end.payments/FaanBreakdown's `Payments` (docs/02-protocol.md §3) for one
	// already-finished hand: that hand's point delta per seat. Sparse for the same reason —
	// a seat with nothing to pay or collect has no entry rather than an explicit 0.
	export interface HandRecord {
		handNo: number;
		dealer: Seat;
		prevailing: Wind;
		deltas: Partial<Record<Seat, number>>;
	}

	// game_end.standings isn't specified beyond the field name (docs/02-protocol.md §3) — score
	// and game_end are still doc-only sketches, unimplemented server-side (no Score/GameEnd model
	// in server/app/protocol.py, nothing generated into protocol.d.ts), same situation
	// FaanBreakdown notes for faan_breakdown/payments. This is the shape decision this component's
	// props codify: ranked order, index 0 = 1st place.
	export interface Standing {
		seat: Seat;
		total: number;
	}

	const WIND_LABEL: Record<Wind, string> = { E: 'East', S: 'South', W: 'West', N: 'North' };
	const RANK_LABEL = ['1st', '2nd', '3rd', '4th'];

	let {
		seats,
		totals,
		hands,
		standings
	}: {
		seats: SeatInfo[];
		totals: Totals;
		hands: HandRecord[];
		standings?: Standing[];
	} = $props();

	function seatName(seat: Seat): string {
		return seats.find((s) => s.seat === seat)?.name ?? `Seat ${seat}`;
	}

	// running total per seat after each hand, derived from `hands` rather than read off `totals`
	// directly — this is the exact arithmetic bug class the component exists to catch: if a
	// hand's deltas don't sum to what `totals` reports, that's wrong data, not a display choice.
	let runningTotals = $derived.by(() => {
		const running: Record<Seat, number> = { 0: 0, 1: 0, 2: 0, 3: 0 };
		const rows: Record<Seat, number>[] = [];
		for (const hand of hands) {
			for (const seat of seats) {
				running[seat.seat] += hand.deltas[seat.seat] ?? 0;
			}
			rows.push({ ...running });
		}
		return rows;
	});

	// after a reconnect mid-game (docs/02-protocol.md §5) a client can hold `totals` from the
	// latest `score` event while `hands` (assembled client-side from `hand_end` events actually
	// seen) is missing earlier hands — `state_sync` replaces state, it doesn't replay history.
	// Flag that instead of silently showing a running-total column that disagrees with the
	// authoritative footer.
	let historyComplete = $derived(
		hands.length === 0 ||
			seats.every((s) => {
				const last = runningTotals[runningTotals.length - 1];
				return last?.[s.seat] === totals[s.seat];
			})
	);
</script>

<section class="score-sheet" aria-labelledby="score-sheet-heading">
	<h2 id="score-sheet-heading">Score sheet</h2>

	<div class="table-scroll">
		<table>
			<thead>
				<tr>
					<th rowspan="2" scope="col">Hand</th>
					<th rowspan="2" scope="col">Wind</th>
					<th rowspan="2" scope="col">Dealer</th>
					{#each seats as seat (seat.seat)}
						<th colspan="2" scope="col">{seat.name}</th>
					{/each}
				</tr>
				<tr>
					{#each seats as seat (seat.seat)}
						<th scope="col" class="sub">+/-</th>
						<th scope="col" class="sub">Total</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each hands as hand, index (hand.handNo)}
					<tr>
						<td>{hand.handNo}</td>
						<td>{WIND_LABEL[hand.prevailing]}</td>
						<td>{seatName(hand.dealer)}</td>
						{#each seats as seat (seat.seat)}
							{@const delta = hand.deltas[seat.seat] ?? 0}
							<td
								class="delta"
								class:delta--gain={delta > 0}
								class:delta--loss={delta < 0}
								class:delta--dealer={seat.seat === hand.dealer}
							>
								{delta > 0 ? '+' : ''}{delta}
							</td>
							<td class="running">{runningTotals[index][seat.seat]}</td>
						{/each}
					</tr>
				{/each}
			</tbody>
			<tfoot>
				<tr>
					<td colspan="3">Total</td>
					{#each seats as seat (seat.seat)}
						<td colspan="2" class="footer-total">{totals[seat.seat]}</td>
					{/each}
				</tr>
			</tfoot>
		</table>
	</div>

	{#if !historyComplete}
		<p class="notice">
			Hand history incomplete (likely a reconnect mid-game) — running totals above may not reach the
			authoritative figures in the footer.
		</p>
	{/if}

	{#if standings}
		<ol class="standings">
			{#each standings as standing, index (standing.seat)}
				<li>
					<span class="rank">{RANK_LABEL[index] ?? `${index + 1}th`}</span>
					<span class="standing-name">{seatName(standing.seat)}</span>
					<span class="standing-total">{standing.total}</span>
				</li>
			{/each}
		</ol>
	{/if}
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.score-sheet {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 36rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.table-scroll {
		overflow-x: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
	}

	th,
	td {
		padding: var(--space-1) var(--space-2);
		text-align: end;
		white-space: nowrap;
	}

	th:first-child,
	td:first-child,
	th:nth-child(2),
	td:nth-child(2),
	th:nth-child(3),
	td:nth-child(3) {
		text-align: start;
	}

	thead th {
		border-bottom: 1px solid var(--color-border);
	}

	thead th.sub {
		font-weight: normal;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	tfoot td {
		border-top: 1px solid var(--color-border);
		font-weight: bold;
	}

	.delta--gain {
		color: var(--color-accent-jade);
	}

	.delta--loss {
		color: var(--color-accent);
	}

	.delta--dealer {
		text-decoration: underline;
		text-decoration-style: dotted;
	}

	.running {
		color: var(--color-text-muted);
	}

	.notice {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.standings {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
		border-top: 1px solid var(--color-border);
		padding-block-start: var(--space-2);
	}

	.standings li {
		display: flex;
		gap: var(--space-3);
		font-variant-numeric: tabular-nums;
	}

	.rank {
		width: 2.5rem;
		color: var(--color-text-muted);
	}

	.standing-name {
		flex: 1;
	}
</style>
