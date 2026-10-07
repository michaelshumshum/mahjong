import { describe, it, expect } from 'vitest';
import { placements } from './rank';

describe('placements', () => {
	it('numbers distinct totals 0..n-1', () => {
		expect(placements([50, 10, -30, -40])).toEqual([0, 1, 2, 3]);
	});

	it('gives tied totals the same place and skips the next', () => {
		expect(placements([50, 10, 10, -70])).toEqual([0, 1, 1, 3]);
	});

	it('handles a tie for first and an all-way tie', () => {
		expect(placements([20, 20, -20, -20])).toEqual([0, 0, 2, 2]);
		expect(placements([0, 0, 0, 0])).toEqual([0, 0, 0, 0]);
	});
});
