import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import ScoreSheet from './ScoreSheet.svelte';
import type { HandRecord, SeatInfo, Standing, Totals } from './ScoreSheet.svelte';

describe('ScoreSheet', () => {
	const seats: SeatInfo[] = [
		{ seat: 0, name: 'Alice' },
		{ seat: 1, name: 'Bob' },
		{ seat: 2, name: 'Carol' },
		{ seat: 3, name: 'Dave' }
	];

	// three hands' worth of deltas, each summing to zero, chosen so the running totals below are
	// easy to hand-check.
	const hands: HandRecord[] = [
		{ handNo: 1, dealer: 0, prevailing: 'E', deltas: { 0: -24, 2: 24 } },
		{ handNo: 2, dealer: 1, prevailing: 'E', deltas: { 0: -16, 1: 48, 2: -16, 3: -16 } },
		{ handNo: 3, dealer: 2, prevailing: 'E', deltas: { 0: 10, 1: 10, 2: -30, 3: 10 } }
	];

	// running totals after each hand (hand-checked against deltas above): {0:-24,2:24} ->
	// {0:-40,1:48,2:8,3:-16} -> {0:-30,1:58,2:-22,3:-6}
	const totals: Totals = { 0: -30, 1: 58, 2: -22, 3: -6 };

	it('renders one row per hand', () => {
		const { body } = render(ScoreSheet, { props: { seats, totals, hands } });
		const tbody = body.match(/<tbody[^>]*>[\s\S]*?<\/tbody>/)?.[0] ?? '';
		expect([...tbody.matchAll(/<tr[\s>]/g)]).toHaveLength(hands.length);
		// strip hydration anchor comments -- they sit between the `<td>` and the digit.
		const stripped = body.replace(/<!--.*?-->/g, '');
		for (const hand of hands) {
			expect(stripped).toMatch(new RegExp(`<td[^>]*>${hand.handNo}</td>`));
		}
	});

	it('running totals match the cumulative sum of deltas, and the footer matches the last row', () => {
		const { body } = render(ScoreSheet, { props: { seats, totals, hands } });

		// after hand 1, Carol (seat 2) is at 24, Alice (seat 0) at -24
		expect(body).toContain('>-24<');
		expect(body).toContain('>24<');
		// after hand 2, Bob (seat 1) is at 48
		expect(body).toContain('>48<');
		// footer (game totals) equals the last hand's running total for every seat
		for (const seat of seats) {
			expect(body).toMatch(new RegExp(`class="footer-total[^"]*">${totals[seat.seat]}<`));
		}
		expect(body).not.toContain('incomplete');
	});

	it('flags an incomplete history when totals disagree with the summed deltas', () => {
		const staleTotals: Totals = { 0: -999, 1: 58, 2: -22, 3: -6 };
		const { body } = render(ScoreSheet, { props: { seats, totals: staleTotals, hands } });
		expect(body).toContain('Hand history incomplete');
	});

	it('renders optional final standings in rank order', () => {
		const standings: Standing[] = [
			{ seat: 1, total: 58 },
			{ seat: 0, total: -30 },
			{ seat: 3, total: -6 },
			{ seat: 2, total: -22 }
		];
		const { body } = render(ScoreSheet, { props: { seats, totals, hands, standings } });
		expect(body).toContain('1st');
		expect(body).toContain('Bob');
		expect(body).toContain('4th');
		expect(body).toContain('Carol');
	});

	it('omits standings when not at game end', () => {
		const { body } = render(ScoreSheet, { props: { seats, totals, hands } });
		expect(body).not.toContain('class="standings"');
	});

	describe('expandable round detail', () => {
		const winResult: HandRecord['result'] = {
			outcome: 'win',
			winner: 2,
			winningHand: ['1m', '2m', '3m'],
			patterns: [{ name: 'Chicken Hand', faan: 1 }],
			totalFaan: 1,
			payments: { 0: -24, 2: 24 }
		};
		const drawResult: HandRecord['result'] = { outcome: 'exhaustive_draw' };
		const handsWithResults: HandRecord[] = [
			{ ...hands[0], result: winResult },
			hands[1],
			{ ...hands[2], result: drawResult }
		];

		it('renders an expand toggle only for a round that carries a result', () => {
			const { body } = render(ScoreSheet, { props: { seats, totals, hands: handsWithResults } });
			expect([...body.matchAll(/class="round-expand(?: [^"]*)?"/g)]).toHaveLength(2);
		});

		it('renders no detail row (server-rendered, collapsed by default) until expanded', () => {
			const { body } = render(ScoreSheet, { props: { seats, totals, hands: handsWithResults } });
			expect(body).not.toContain('id="round-detail-1"');
			expect(body).toMatch(/aria-expanded="false"/);
		});

		// svelte/server only renders the initial (collapsed) markup -- expand-to-reveal is
		// covered end-to-end (routes/demo/demo.e2e.ts).
	});
});
