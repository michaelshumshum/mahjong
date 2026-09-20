import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import FaanBreakdown from './FaanBreakdown.svelte';
import type { FaanPattern, Payments, WinningMeld } from './FaanBreakdown.svelte';

describe('FaanBreakdown', () => {
	const patterns: FaanPattern[] = [
		{ name: 'All Sequences', faan: 1 },
		{ name: 'No Flowers', faan: 1 },
		{ name: 'Half Flush', faan: 3 }
	];
	// discard win: seat 0 discarded into seat 2's 5-faan hand, half_spicy P(5) = 24
	const payments: Payments = { 0: -24, 2: 24 };

	it('renders one row per matched pattern', () => {
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: [], patterns, totalFaan: 5, payments }
		});
		expect([...body.matchAll(/class="pattern-row[^"]*"/g)]).toHaveLength(3);
		expect(body).toContain('All Sequences');
		expect(body).toContain('Half Flush');
	});

	it('shows the plain total when the pattern sum is within the cap', () => {
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: [], patterns, totalFaan: 5, payments }
		});
		expect(body).toContain('5 faan');
		expect(body).not.toContain('capped from');
	});

	it('flags a capped total when the pattern sum exceeds the given total', () => {
		// Full Flush (6) + All Pungs (3) + Two Dragon Pungs (2) = 11, clamped to faan_cap 10
		// (docs/01-rules-spec.md §7 stacking example + "Total is clamped").
		const stacked: FaanPattern[] = [
			{ name: 'Full Flush', faan: 6 },
			{ name: 'All Pungs', faan: 3 },
			{ name: 'Two Dragon Pungs', faan: 2 }
		];
		// self-draw, half_spicy P(10) = 128: winner +1.5P, each of 3 losers -0.5P
		const selfDrawPayments: Payments = { 0: -64, 1: -64, 2: 192, 3: -64 };
		const { body } = render(FaanBreakdown, {
			props: {
				winner: 2,
				winningHand: [],
				patterns: stacked,
				totalFaan: 10,
				payments: selfDrawPayments
			}
		});
		expect(body).toContain('10 faan');
		expect(body).toContain('capped from 11');
	});

	it('renders payment rows with signed amounts per seat, winner and payer only', () => {
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: [], patterns, totalFaan: 5, payments }
		});
		expect([...body.matchAll(/class="payment-row[^"]*"/g)]).toHaveLength(2);
		expect(body).toContain('+24');
		expect(body).toContain('-24');
	});

	it('names the winning seat in the heading', () => {
		const { body } = render(FaanBreakdown, {
			props: { winner: 3, winningHand: [], patterns, totalFaan: 5, payments: { 3: 24, 1: -24 } }
		});
		expect(body).toContain('North wins');
	});

	it('sorts the concealed hand by suit and rank regardless of wire order', () => {
		const { body } = render(FaanBreakdown, {
			props: {
				winner: 2,
				winningHand: ['9s', '1m', 'z5', '1s', '5p'],
				patterns,
				totalFaan: 5,
				payments
			}
		});
		const order = [...body.matchAll(/alt="([^"]+) tile"/g)].map((m) => m[1]);
		expect(order).toEqual(['1m', '5p', '1s', '9s', 'z5']);
	});

	it('renders claimed melds separately from, and before, the concealed hand', () => {
		const melds: WinningMeld[] = [{ kind: 'pung', tiles: ['9s', '9s', '9s'] }];
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: ['1m', '2m', '3m'], melds, patterns, totalFaan: 5, payments }
		});
		expect(body).toMatch(/class="melds\b/);
		expect(body).toMatch(/class="concealed-hand\b/);
		const order = [...body.matchAll(/alt="([^"]+) tile"/g)].map((m) => m[1]);
		expect(order).toEqual(['9s', '9s', '9s', '1m', '2m', '3m']);
	});

	it('renders no meld group when there are no claimed melds', () => {
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: ['1m', '2m', '3m'], patterns, totalFaan: 5, payments }
		});
		expect(body).not.toMatch(/class="melds\b/);
		expect(body).toMatch(/class="concealed-hand\b/);
	});

	it('renders a concealed_kong meld as backs, matching the in-play convention', () => {
		const melds: WinningMeld[] = [{ kind: 'concealed_kong', tiles: ['z1', 'z1', 'z1', 'z1'] }];
		const { body } = render(FaanBreakdown, {
			props: { winner: 2, winningHand: [], melds, patterns, totalFaan: 5, payments }
		});
		expect(body).toContain('concealed tile');
		expect(body).not.toContain('alt="z1 tile"');
	});
});
