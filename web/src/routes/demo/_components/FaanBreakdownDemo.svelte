<script lang="ts">
	import FaanBreakdown, {
		type FaanPattern,
		type Payments,
		type WinningMeld
	} from '$lib/ui/FaanBreakdown.svelte';

	const seatNames: Record<0 | 1 | 2 | 3, string> = {
		0: 'Alice',
		1: 'Bob',
		2: 'Carol',
		3: 'Dave'
	};

	// mock hand_end data, no real scoring yet. Patterns sourced from docs/01-rules-spec.md §7.
	// plain hand: discard win, 5 faan, half_spicy P(5) = 24.
	const plainPatterns: FaanPattern[] = [
		{ name: 'All Sequences', faan: 1 },
		{ name: 'No Flowers', faan: 1 },
		{ name: 'Fully Concealed', faan: 1 },
		{ name: 'Half Flush', faan: 3 }
	];
	const plainPayments: Payments = { 0: -24, 2: 24 };

	// Capped hand: Full Flush (6) + All Pungs (3) + Self-Draw (1) + No Flowers (1) = 11, clamped
	// to the default faan_cap of 10. Self-draw, half_spicy P(10) = 128: winner +1.5P, others -0.5P.
	const cappedPatterns: FaanPattern[] = [
		{ name: 'Full Flush', faan: 6 },
		{ name: 'All Pungs', faan: 3 },
		{ name: 'Self-Draw', faan: 1 },
		{ name: 'No Flowers', faan: 1 }
	];
	const cappedPayments: Payments = { 0: -64, 1: -64, 2: 192, 3: -64 };
	// one pung was claimed off a discard -- All Pungs doesn't care concealed vs exposed, so this
	// also exercises FaanBreakdown's claimed/in-hand split.
	const cappedMelds: WinningMeld[] = [{ kind: 'pung', tiles: ['1s', '1s', '1s'] }];
</script>

<h2>FaanBreakdown demo</h2>
<p class="hint">
	Mock <code>hand_end</code> data (docs/02-protocol.md §3) — no real scoring exists yet. First card:
	a plain 5-faan discard win. Second: four patterns stacking to 11 faan, clamped to the default
	<code>faan_cap</code> of 10.
</p>
<div class="breakdown-row">
	<FaanBreakdown
		winner={2}
		{seatNames}
		winningHand={[
			'1s',
			'2s',
			'3s',
			'4s',
			'5s',
			'6s',
			'7s',
			'8s',
			'9s',
			'2s',
			'3s',
			'4s',
			'z5',
			'z5'
		]}
		patterns={plainPatterns}
		totalFaan={5}
		payments={plainPayments}
	/>
	<FaanBreakdown
		winner={2}
		{seatNames}
		winningHand={['3s', '3s', '3s', '5s', '5s', '5s', '7s', '7s', '7s', '9s', '9s']}
		melds={cappedMelds}
		patterns={cappedPatterns}
		totalFaan={10}
		payments={cappedPayments}
	/>
</div>

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.breakdown-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-4);
	}
</style>
