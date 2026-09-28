<script lang="ts">
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';
	import { m } from '$lib/paraglide/messages.js';

	// mock score/game_end data. EAST_ONLY (一圈) means a full game is one round, so 4 hands here
	// is the minimum length, not a fixed count. Deltas hand-checked to sum to zero per hand.
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
			// expandable, reveals Carol's winning hand inline via the same FaanBreakdown.
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

<h2>{m.scoreSheetDemo_heading()}</h2>
<p class="hint">
	{m.scoreSheetDemo_hintIntro()} <code>score</code>/<code>game_end</code>
	{m.scoreSheetDemo_hintBody()}<code>EAST_ONLY</code>{m.scoreSheetDemo_hintTail()}
</p>
<ScoreSheet seats={scoreSeats} totals={scoreTotals} hands={scoreHands} standings={scoreStandings} />

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
