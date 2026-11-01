import { describe, expect, it } from 'vitest';
import defence02 from './generated/defence-02.json';
import efficiency02 from './generated/efficiency-02.json';
import faan03 from './generated/faan-03.json';
import keepTwoSided from './generated/basics-keep-two-sided.json';
import waits12 from './generated/waits-12.json';
import type {
	BestDiscardKey,
	CountFaanKey,
	SafeDiscardKey,
	WinningTilesKey
} from './generated/lessons';
import {
	discardComparison,
	discardRows,
	faanMiss,
	safeOutcome,
	safeRows,
	waitsFeedback
} from './feedback';

const discardKey = efficiency02.key as BestDiscardKey;
const waitsKey = waits12.key as WinningTilesKey;
const safeKey = defence02.key as SafeDiscardKey;
const faanKey = faan03.key as CountFaanKey;

describe('discardRows', () => {
	it('lists every option best first, marking the answers and the pick', () => {
		const rows = discardRows(discardKey, '3m');
		expect(rows).toHaveLength(discardKey.options.length);
		expect(rows.slice(0, 2).map((r) => r.tile)).toEqual(['9p', '4s']);
		expect(rows.filter((r) => r.correct).map((r) => r.tile)).toEqual(['9p', '4s']);
		expect(rows.filter((r) => r.picked).map((r) => r.tile)).toEqual(['3m']);
		const later = rows.slice(2);
		expect(later.every((r, i) => i === 0 || r.tiles <= later[i - 1].tiles)).toBe(true);
	});
});

describe('discardComparison', () => {
	it('pairs a wrong pick with the first answer', () => {
		const cmp = discardComparison(keepTwoSided.key as BestDiscardKey, '2m');
		expect(cmp?.pick).toMatchObject({ tile: '2m', shanten: 0, tiles: 7 });
		expect(cmp?.best).toMatchObject({ tile: '5m', shanten: 0, tiles: 10 });
	});

	it('is null for a right pick', () => {
		expect(discardComparison(discardKey, '4s')).toBeNull();
	});
});

describe('waitsFeedback', () => {
	it('reads each pick: wins, below the minimum, dead, or no win', () => {
		const fb = waitsFeedback(waitsKey, ['9m', '4p', '2p', '1p']);
		expect(fb.picks.map((p) => [p.tile, p.verdict])).toEqual([
			['9m', 'no_win'],
			['1p', 'wins'],
			['2p', 'below_minimum'],
			['4p', 'dead']
		]);
		expect(fb.picks[2].option).toMatchObject({ discard_faan: 1, self_draw_faan: 2 });
		expect(fb.missing).toBe(1);
	});

	it('lists the below-minimum and dead waits from the key', () => {
		const fb = waitsFeedback(waitsKey, ['1p', '7p']);
		expect(fb.missing).toBe(0);
		expect(fb.belowMinimum.map((o) => o.tile)).toEqual(['2p', '5p']);
		expect(fb.dead.map((o) => o.tile)).toEqual(['4p']);
	});
});

describe('safe discard', () => {
	it('tells deducible, lucky and dealing-in tiles apart', () => {
		expect(safeOutcome(safeKey, '8s')).toBe('deducible');
		expect(safeOutcome(safeKey, '2m')).toBe('lucky');
		expect(safeOutcome(safeKey, 'z5')).toBe('deals_in');
	});

	it('keeps every hand tile, with who it deals in to', () => {
		const rows = safeRows(safeKey, '2m');
		expect(rows).toHaveLength(safeKey.options.length);
		expect(rows.find((r) => r.picked)?.tile).toBe('2m');
		expect(rows.find((r) => r.tile === 'z5')).toMatchObject({
			outcome: 'deals_in',
			deals_in_to: [2]
		});
	});
});

describe('faanMiss', () => {
	it('says which way a wrong count missed', () => {
		expect(faanMiss(faanKey, 6)).toBeNull();
		expect(faanMiss(faanKey, 7)).toBe('high');
		expect(faanMiss(faanKey, 5)).toBe('low');
	});
});
