import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import WinningHand from './WinningHand.svelte';
import type { FaanPattern, WinningMeld } from './WinningHand.svelte';

describe('WinningHand', () => {
	const patterns: FaanPattern[] = [
		{ name: 'All Sequences', faan: 1 },
		{ name: 'No Flowers', faan: 1 },
		{ name: 'Half Flush', faan: 3 }
	];

	it('renders one row per matched pattern', () => {
		const { body } = render(WinningHand, {
			props: { winningHand: [], patterns, totalFaan: 5 }
		});
		expect([...body.matchAll(/class="pattern-row[^"]*"/g)]).toHaveLength(3);
		expect(body).toContain('All Sequences');
		expect(body).toContain('Half Flush');
	});

	it('shows the plain total when the pattern sum is within the cap', () => {
		const { body } = render(WinningHand, {
			props: { winningHand: [], patterns, totalFaan: 5 }
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
		const { body } = render(WinningHand, {
			props: { winningHand: [], patterns: stacked, totalFaan: 10 }
		});
		expect(body).toContain('10 faan');
		expect(body).toContain('capped from 11');
	});

	it('sorts the concealed hand by suit and rank regardless of wire order', () => {
		const { body } = render(WinningHand, {
			props: { winningHand: ['9s', '1m', 'z5', '1s', '5p'], patterns, totalFaan: 5 }
		});
		const order = [...body.matchAll(/alt="([^"]+) tile"/g)].map((m) => m[1]);
		expect(order).toEqual(['1m', '5p', '1s', '9s', 'z5']);
	});

	it('renders claimed melds separately from, and before, the concealed hand', () => {
		const melds: WinningMeld[] = [{ kind: 'pung', tiles: ['9s', '9s', '9s'] }];
		const { body } = render(WinningHand, {
			props: { winningHand: ['1m', '2m', '3m'], melds, patterns, totalFaan: 5 }
		});
		expect(body).toMatch(/class="melds\b/);
		expect(body).toMatch(/class="concealed-hand\b/);
		const order = [...body.matchAll(/alt="([^"]+) tile"/g)].map((m) => m[1]);
		expect(order).toEqual(['9s', '9s', '9s', '1m', '2m', '3m']);
	});

	it('renders no meld group when there are no claimed melds', () => {
		const { body } = render(WinningHand, {
			props: { winningHand: ['1m', '2m', '3m'], patterns, totalFaan: 5 }
		});
		expect(body).not.toMatch(/class="melds\b/);
		expect(body).toMatch(/class="concealed-hand\b/);
	});

	it('renders a concealed_kong meld as backs, matching the in-play convention', () => {
		const melds: WinningMeld[] = [{ kind: 'concealed_kong', tiles: ['z1', 'z1', 'z1', 'z1'] }];
		const { body } = render(WinningHand, {
			props: { winningHand: [], melds, patterns, totalFaan: 5 }
		});
		expect(body).toContain('concealed tile');
		expect(body).not.toContain('alt="z1 tile"');
	});

	it('exposes an aria-label on the section for screen readers', () => {
		const { body } = render(WinningHand, {
			props: { winningHand: ['1m'], patterns, totalFaan: 5 }
		});
		expect(body).toMatch(/<section class="winning-hand-summary[^"]*" aria-label="[^"]+"/);
	});
});
