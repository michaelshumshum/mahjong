import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import CenterDiscardPool from './CenterDiscardPool.svelte';
import type { MockSeatState } from './mock-game-state';

function mockSeat(overrides: Partial<MockSeatState> = {}): MockSeatState {
	return {
		seat: 0,
		name: 'You',
		concealedCount: 13,
		melds: [],
		discards: [],
		flowers: [],
		score: 0,
		...overrides
	};
}

describe('CenterDiscardPool', () => {
	afterEach(cleanupAll);

	it('renders one tile per discard', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat({ discards: ['1m', '2m', '3m'] }),
			position: 'self',
			ariaLabel: 'Your discards'
		});
		expect(target.querySelectorAll('.discard-tile')).toHaveLength(3);
	});

	it('applies the position modifier class', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat({ discards: ['1m'] }),
			position: 'across',
			ariaLabel: 'Across discards'
		});
		expect(target.querySelector('.discard-pool--across')).not.toBeNull();
	});

	it('exposes the list role and aria-label', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat(),
			position: 'left',
			ariaLabel: 'Left discards'
		});
		const pool = target.querySelector('.discard-pool');
		expect(pool?.getAttribute('role')).toBe('list');
		expect(pool?.getAttribute('aria-label')).toBe('Left discards');
	});

	it('renders each discard as a listitem with a tile face', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat({ discards: ['5s', 'z5'] }),
			position: 'right',
			ariaLabel: 'Right discards'
		});
		const items = target.querySelectorAll('[role="listitem"]');
		expect(items).toHaveLength(2);
		expect(target.innerHTML).toContain('src="/tiles/Sou5.svg"');
		expect(target.innerHTML).toContain('src="/tiles/Chun.svg"');
	});

	it('renders an empty pool with no tiles', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat(),
			position: 'self',
			ariaLabel: 'Empty discards'
		});
		expect(target.querySelectorAll('.discard-tile')).toHaveLength(0);
	});

	it('marks the tile at lastDiscardIndex and no other', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat({ discards: ['1m', '2m', '3m'], name: 'Carol' }),
			position: 'self',
			ariaLabel: 'Your discards',
			lastDiscardIndex: 1
		});
		const tiles = target.querySelectorAll('.discard-tile');
		expect(tiles[0].classList.contains('discard-tile--last')).toBe(false);
		expect(tiles[1].classList.contains('discard-tile--last')).toBe(true);
		expect(tiles[2].classList.contains('discard-tile--last')).toBe(false);
		expect(tiles[1].getAttribute('title')).toBe('Carol discarded');
	});

	it('marks nothing when lastDiscardIndex is null', () => {
		const { target } = render(CenterDiscardPool, {
			seat: mockSeat({ discards: ['1m', '2m'] }),
			position: 'self',
			ariaLabel: 'Your discards',
			lastDiscardIndex: null
		});
		expect(target.querySelectorAll('.discard-tile--last')).toHaveLength(0);
	});
});
