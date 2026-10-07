<script lang="ts">
	import WinningHand, { type FaanPattern, type WinningMeld } from './WinningHand.svelte';
	import type { TileCode } from '../table/tile-code';
	import { placements, rankLabel, RANK_TONE } from './rank';
	import { m } from '$lib/paraglide/messages.js';

	export type Seat = 0 | 1 | 2 | 3;
	export type Wind = 'E' | 'S' | 'W' | 'N';

	// mirrors hand_end.payments (docs/protocol.md §3): per-seat point delta for one hand.
	export type Payments = Partial<Record<Seat, number>>;

	export interface SeatInfo {
		seat: Seat;
		name: string;
	}

	// mirrors score.totals: authoritative running total per seat, last received from the server.
	// Kept as its own prop rather than derived only from `hands` -- see `historyComplete`.
	export type Totals = Record<Seat, number>;

	// mirrors hand_end.payments for one already-finished hand. Sparse: a seat with nothing to
	// pay or collect has no entry rather than an explicit 0.
	export interface HandRecord {
		handNo: number;
		dealer: Seat;
		prevailing: Wind;
		deltas: Partial<Record<Seat, number>>;
		/** Optional per-round detail -- present, this round's row becomes expandable, revealing
		 * the winning hand or a plain draw note inline via `WinningHand`. */
		result?: RoundResult;
	}

	export interface RoundResult {
		outcome: 'win' | 'exhaustive_draw';
		winner?: Seat;
		winningHand?: TileCode[];
		melds?: WinningMeld[];
		patterns?: FaanPattern[];
		totalFaan?: number;
		payments?: Payments;
	}

	// `game_end` only ever carries {hand_no, scores} -- absolute totals, no ranking baked in.
	// `standings` (ranked order, index 0 = 1st) is left for a caller to fill in when it has one.
	export interface Standing {
		seat: Seat;
		total: number;
	}

	function windLabel(wind: Wind): string {
		switch (wind) {
			case 'E':
				return m.scoreSheet_windEast();
			case 'S':
				return m.scoreSheet_windSouth();
			case 'W':
				return m.scoreSheet_windWest();
			case 'N':
				return m.scoreSheet_windNorth();
		}
	}

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

	// tied totals share a place ("1224"), matching GameEndScreen.
	let standingPlaces = $derived(placements((standings ?? []).map((s) => s.total)));

	function seatName(seat: Seat): string {
		return seats.find((s) => s.seat === seat)?.name ?? m.scoreSheet_seatFallbackLabel({ seat });
	}

	let seatNames = $derived(
		Object.fromEntries(seats.map((s) => [s.seat, s.name])) as Record<Seat, string>
	);

	// derived from `hands` rather than read off `totals` directly -- if a hand's deltas don't
	// sum to what `totals` reports, that's the bug this component exists to catch.
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

	// safety net, not the expected case: flags a running-total column that disagrees with the
	// authoritative `totals` footer, in case the two ever diverge.
	let historyComplete = $derived(
		hands.length === 0 ||
			seats.every((s) => {
				const last = runningTotals[runningTotals.length - 1];
				return last?.[s.seat] === totals[s.seat];
			})
	);

	// which rounds' detail panel is open, keyed by handNo — presentation state, not game truth.
	let expandedHands = $state<Set<number>>(new Set());

	function toggleExpanded(handNo: number): void {
		const next = new Set(expandedHands);
		if (next.has(handNo)) next.delete(handNo);
		else next.add(handNo);
		expandedHands = next;
	}

	// Hand/Wind/Dealer + two columns per seat -- so the detail row's colspan spans the full table.
	let columnCount = $derived(3 + seats.length * 2);
</script>

<section class="score-sheet" aria-labelledby="score-sheet-heading">
	<header class="score-sheet-header"></header>

	<div class="table-scroll">
		<table>
			<thead>
				<tr>
					<th rowspan="2" scope="col" class="col-hand">{m.scoreSheet_handColumnHeader()}</th>
					<th rowspan="2" scope="col" class="col-wind">{m.scoreSheet_windColumnHeader()}</th>
					<th rowspan="2" scope="col" class="col-dealer">{m.scoreSheet_dealerColumnHeader()}</th>
					{#each seats as seat (seat.seat)}
						<th colspan="2" scope="colgroup" class="col-seat">
							{seat.name}
						</th>
					{/each}
				</tr>
				<tr>
					{#each seats as seat (seat.seat)}
						<th scope="col" class="sub">{m.scoreSheet_deltaColumnHeader()}</th>
						<th scope="col" class="sub">{m.scoreSheet_totalColumnHeader()}</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each hands as hand, index (hand.handNo)}
					{@const isExpanded = expandedHands.has(hand.handNo)}
					<tr>
						<td class="col-hand">
							{#if hand.result}
								<button
									type="button"
									class="round-expand"
									aria-expanded={isExpanded}
									aria-controls="round-detail-{hand.handNo}"
									onclick={() => toggleExpanded(hand.handNo)}
								>
									<span class="round-expand-icon" aria-hidden="true">{isExpanded ? '▾' : '▸'}</span>
									<span class="round-expand-label">{hand.handNo}</span>
								</button>
							{:else}
								{hand.handNo}
							{/if}
						</td>
						<td class="col-wind">{windLabel(hand.prevailing)}</td>
						<td class="col-dealer">
							{#if seatName(hand.dealer)}
								<span class="dealer-badge">{seatName(hand.dealer)}</span>
							{/if}
						</td>
						{#each seats as seat (seat.seat)}
							{@const delta = hand.deltas[seat.seat] ?? 0}
							{@const isDealer = seat.seat === hand.dealer}
							<td
								class="delta"
								class:delta--gain={delta > 0}
								class:delta--loss={delta < 0}
								class:delta--dealer={isDealer}
							>
								{delta > 0 ? '+' : ''}{delta}
							</td>
							<td class="running" class:running--dealer={isDealer}>
								{runningTotals[index][seat.seat]}
							</td>
						{/each}
					</tr>
					{#if hand.result && isExpanded}
						<tr class="round-detail-row" id="round-detail-{hand.handNo}">
							<td colspan={columnCount}>
								{#if hand.result.outcome === 'win' && hand.result.winner !== undefined}
									<WinningHand
										winningHand={hand.result.winningHand ?? []}
										melds={hand.result.melds ?? []}
										patterns={hand.result.patterns ?? []}
										totalFaan={hand.result.totalFaan ?? 0}
									/>
								{:else}
									<p class="draw-note">{m.scoreSheet_exhaustiveDrawNote()}</p>
								{/if}
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
			<tfoot>
				<tr>
					<td colspan="3" class="footer-label">{m.scoreSheet_totalColumnHeader()}</td>
					{#each seats as seat (seat.seat)}
						<td colspan="2" class="footer-total">{totals[seat.seat]}</td>
					{/each}
				</tr>
			</tfoot>
		</table>
	</div>

	{#if !historyComplete}
		<p class="notice">
			{m.scoreSheet_historyIncompleteNotice()}
		</p>
	{/if}

	{#if standings}
		<div class="standings">
			<h3 class="standings-heading">{m.scoreSheet_finalStandingsHeading()}</h3>
			<ol class="standings-list">
				{#each standings as standing, i (standing.seat)}
					{@const index = standingPlaces[i]}
					<li class="standing-card" class:standing-card--top={index < 3}>
						<span
							class="rank"
							style:background={RANK_TONE[index] ?? 'transparent'}
							style:color={index < 3 ? 'var(--color-tile-ink)' : 'var(--color-text-muted)'}
						>
							{rankLabel(index)}
						</span>
						<span class="standing-name">{seatName(standing.seat)}</span>
						<span
							class="standing-total"
							class:standing-total--positive={standing.total > 0}
							class:standing-total--negative={standing.total < 0}
						>
							{standing.total > 0 ? '+' : ''}{standing.total}
						</span>
					</li>
				{/each}
			</ol>
		</div>
	{/if}
</section>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.score-sheet {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(90vw, 56rem);
		max-width: 90vw;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6);
		}
	}

	.score-sheet-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-3);
	}

	.table-scroll {
		overflow-x: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	table {
		width: 100%;
		border-collapse: collapse;
		font-variant-numeric: tabular-nums;
		font-size: var(--font-size-base);
	}

	th,
	td {
		padding: var(--space-2) var(--space-3);
		text-align: end;
		white-space: nowrap;
	}

	.col-hand,
	.col-wind,
	.col-dealer,
	td:first-child,
	td:nth-child(2),
	td:nth-child(3) {
		text-align: start;
	}

	thead {
		position: sticky;
		top: 0;
		z-index: 1;
		background: var(--color-surface-raised);
	}

	thead th {
		border-bottom: 1px solid var(--color-border);
		font-weight: 700;
	}

	thead th.sub {
		font-weight: 600;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	tbody tr:nth-child(even of :not(.round-detail-row)) {
		background: rgb(255 255 255 / 0.02);
	}

	tbody tr:hover:not(.round-detail-row) {
		background: rgb(255 255 255 / 0.05);
	}

	tfoot td {
		border-top: 2px solid var(--color-border);
		font-weight: 800;
		font-size: var(--font-size-lg);
	}

	.footer-label {
		color: var(--color-text-muted);
		font-size: var(--font-size-base);
	}

	.footer-total {
		color: var(--color-text);
	}

	.delta--gain {
		color: var(--color-positive);
		font-weight: 700;
	}

	.delta--loss {
		color: var(--color-negative);
		font-weight: 700;
	}

	.delta--dealer {
		background: color-mix(in srgb, var(--color-brass) 12%, transparent);
	}

	.running {
		color: var(--color-text-muted);
	}

	.running--dealer {
		background: color-mix(in srgb, var(--color-brass) 12%, transparent);
	}

	.dealer-badge {
		display: inline-block;
		padding: var(--space-1) var(--space-2);
		border-radius: var(--radius-sm);
		background: color-mix(in srgb, var(--color-brass) 18%, transparent);
		color: var(--color-brass);
		font-size: var(--font-size-sm);
		font-weight: 700;
	}

	.round-expand {
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		padding: var(--space-1) var(--space-2);
		color: inherit;
		font: inherit;
		font-variant-numeric: tabular-nums;
		font-weight: 700;
		cursor: pointer;
		transition:
			background-color 130ms ease,
			border-color 130ms ease,
			color 130ms ease;

		&:hover {
			border-color: var(--color-accent);
			background: var(--color-bg);
			color: var(--color-accent-on-dark);
		}
	}

	.round-expand-icon {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.round-detail-row td {
		padding: var(--space-4) var(--space-3);
		background: var(--color-bg);
		text-align: start;
	}

	.draw-note {
		margin: 0;
		padding: var(--space-4);
		color: var(--color-text-muted);
		font-size: var(--font-size-lg);
		text-align: center;
	}

	.notice {
		margin: 0;
		padding: var(--space-3);
		border-radius: var(--radius-sm);
		background: rgb(231 126 64 / 0.12);
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.standings {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		border-top: 1px solid var(--color-border);
		padding-block-start: var(--space-4);
	}

	.standings-heading {
		margin: 0;
		font-size: var(--font-size-lg);
		font-weight: 700;
		color: var(--color-text-muted);
	}

	.standings-list {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr));
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.standing-card {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		font-variant-numeric: tabular-nums;
		transition: background-color 130ms ease;

		&:hover {
			background: rgb(255 255 255 / 0.03);
		}
	}

	.standing-card--top {
		border-color: color-mix(in srgb, var(--color-border) 70%, var(--color-accent) 30%);
		background: rgb(255 255 255 / 0.04);
	}

	.rank {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 50%;
		font-weight: 800;
		font-size: var(--font-size-base);
	}

	.standing-name {
		flex: 1;
		font-weight: 700;
		font-size: var(--font-size-lg);
	}

	.standing-total {
		font-size: var(--font-size-xl);
		font-weight: 800;
	}

	.standing-total--positive {
		color: var(--color-positive);
	}

	.standing-total--negative {
		color: var(--color-negative);
	}
</style>
