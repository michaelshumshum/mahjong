import { describe, expect, it } from 'vitest';
import { moveTile, reconcileHandOrder } from './hand-order';

describe('reconcileHandOrder', () => {
	it('starts from the auto-sorted order when nothing is arranged yet', () => {
		expect(reconcileHandOrder([], [4, 8, 12])).toEqual([4, 8, 12]);
	});

	it('keeps the arrangement, drops tiles no longer held, and appends new ones', () => {
		expect(reconcileHandOrder([12, 4, 8], [4, 12, 20, 16])).toEqual([12, 4, 20, 16]);
	});

	it('is stable once reconciled', () => {
		const once = reconcileHandOrder([12, 4, 8], [4, 8, 12, 20]);
		expect(reconcileHandOrder(once, [4, 8, 12, 20])).toEqual(once);
	});
});

describe('moveTile', () => {
	it('moves a tile left and right', () => {
		expect(moveTile([1, 2, 3, 4], 4, 0)).toEqual([4, 1, 2, 3]);
		expect(moveTile([1, 2, 3, 4], 1, 2)).toEqual([2, 3, 1, 4]);
	});

	it('clamps the target index and ignores unknown tiles', () => {
		expect(moveTile([1, 2, 3], 1, 99)).toEqual([2, 3, 1]);
		expect(moveTile([1, 2, 3], 2, -5)).toEqual([2, 1, 3]);
		expect(moveTile([1, 2, 3], 9, 0)).toEqual([1, 2, 3]);
	});
});
