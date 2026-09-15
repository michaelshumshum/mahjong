import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import FaanBreakdown from './FaanBreakdown.svelte';
import type { FaanPattern, Payments } from './FaanBreakdown.svelte';

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
});
