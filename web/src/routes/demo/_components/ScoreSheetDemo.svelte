<script lang="ts">
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';

	// ScoreSheet demo (this sub-task): mock score/game_end data — like hand_end above, still
	// doc-only sketches with no server model yet (docs/02-protocol.md §3). EAST_ONLY (一圈,
	// docs/05-roadmap.md §5 resolved decision #3) means a full game is one round: dealer stays on
	// a win/draw, otherwise passes counter-clockwise, so a 4-hand game here is the *minimum*
	// length, not a fixed count. Deltas below are hand-checked to sum to zero per hand and to
	// accumulate exactly to `scoreTotals`.
	const scoreSeats: SeatInfo[] = [
		{ seat: 0, name: 'Alice' },
		{ seat: 1, name: 'Bob' },
		{ seat: 2, name: 'Carol' },
		{ seat: 3, name: 'Dave' }
	];
	const scoreHands: HandRecord[] = [
		{
			handNo: 1,
			dealer: 0,
			prevailing: 'E',
			deltas: { 0: -24, 2: 24 },
			// per-round detail (this sub-task): expandable, reveals Carol's winning hand inline
			// via the same FaanBreakdown the hand-end overlay and the FaanBreakdown demo above use.
			result: {
				outcome: 'win',
				winner: 2,
				winningHand: ['1s', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', 'z5', 'z5'],
				melds: [{ kind: 'chow', tiles: ['2s', '3s', '4s'] }],
				patterns: [{ name: 'Half Flush', faan: 3 }],
				totalFaan: 3,
				payments: { 0: -24, 2: 24 }
			}
		},
		{ handNo: 2, dealer: 1, prevailing: 'E', deltas: { 0: -16, 1: 48, 2: -16, 3: -16 } },
		{
			handNo: 3,
			dealer: 2,
			prevailing: 'E',
			deltas: { 0: 10, 1: 10, 2: -30, 3: 10 },
			// exhaustive draw: expandable too, but with no winning hand to show.
			result: { outcome: 'exhaustive_draw' }
		},
		{ handNo: 4, dealer: 3, prevailing: 'E', deltas: { 1: -8, 2: -8, 3: 16 } }
	];
	// running total after hand 4: {0:-30, 1:50, 2:-30, 3:10}
	const scoreTotals: Totals = { 0: -30, 1: 50, 2: -30, 3: 10 };
	const scoreStandings: Standing[] = [
		{ seat: 1, total: 50 },
		{ seat: 3, total: 10 },
		{ seat: 0, total: -30 },
		{ seat: 2, total: -30 }
	];
</script>

<h2>ScoreSheet demo</h2>
<p class="hint">
	Mock <code>score</code>/<code>game_end</code> data (docs/02-protocol.md §3) — like the
	FaanBreakdown demo above, no real server model exists for these events yet. Four hands of a
	one-round (<code>EAST_ONLY</code>, 一圈) game; deltas per hand sum to zero and accumulate to the
	footer totals and final standings shown below. Hands 1 and 3 carry per-round detail — click their
	row to expand the winning hand (or the draw note).
</p>
<ScoreSheet seats={scoreSeats} totals={scoreTotals} hands={scoreHands} standings={scoreStandings} />

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
