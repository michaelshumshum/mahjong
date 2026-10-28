import { describe, expect, it, vi } from 'vitest';
import {
	findRawClaimOption,
	legalClaimOptions,
	legalDeclareOptions,
	legalDiscardIds
} from './legal-actions';
import type { ClaimWindowView } from './view-types';

function intents() {
	return { win: vi.fn(), concealedKong: vi.fn(), addedKong: vi.fn() };
}

describe('legalDiscardIds', () => {
	it('collects only discard actions', () => {
		const ids = legalDiscardIds([
			{ kind: 'discard', tile_id: 4 },
			{ kind: 'discard', tile_id: 37 },
			{ kind: 'declare_win' },
			{ kind: 'declare_concealed_kong', meld: { tiles: [0, 1, 2, 3] } }
		]);
		expect([...ids].sort((a, b) => a - b)).toEqual([4, 37]);
	});

	it('is empty off turn', () => {
		expect(legalDiscardIds([]).size).toBe(0);
	});
});

describe('legalDeclareOptions', () => {
	it('maps each declare kind to an option wired to its intent', () => {
		const calls = intents();
		const options = legalDeclareOptions(
			[
				{ kind: 'discard', tile_id: 4 },
				{ kind: 'declare_win' },
				{ kind: 'declare_concealed_kong', meld: { tiles: [0, 1, 2, 3] } },
				{ kind: 'declare_added_kong', meld: { tiles: [36, 37, 38, 39] } }
			],
			calls
		);
		expect(options.map((o) => o.key)).toEqual(['win', 'ck-0,1,2,3', 'ak-36,37,38,39']);
		expect(options[0].hero).toBe(true);
		expect(options[1].tiles).toEqual(['1m', '1m', '1m', '1m']);
		expect(options[2].tiles).toEqual(['1p', '1p', '1p', '1p']);

		for (const option of options) option.onClick();
		expect(calls.win).toHaveBeenCalledOnce();
		expect(calls.concealedKong).toHaveBeenCalledWith([0, 1, 2, 3]);
		expect(calls.addedKong).toHaveBeenCalledWith([36, 37, 38, 39]);
	});

	it('skips a kong with no meld tiles', () => {
		expect(legalDeclareOptions([{ kind: 'declare_concealed_kong' }], intents())).toEqual([]);
	});
});

describe('legalClaimOptions', () => {
	const window: ClaimWindowView = {
		windowId: 7,
		kind: 'discard',
		sourceSeat: 3,
		tile: '5s',
		durationMs: 5000,
		yourOptions: [{ kind: 'pung', tiles: ['5s', '5s'] }, { kind: 'pass' }]
	};

	it('is null with no window or no offer for this seat', () => {
		expect(legalClaimOptions(null)).toBeNull();
		expect(legalClaimOptions({ ...window, yourOptions: null })).toBeNull();
	});

	it('copies this seat’s offered options', () => {
		expect(legalClaimOptions(window)).toEqual([
			{ kind: 'pung', tiles: ['5s', '5s'] },
			{ kind: 'pass', tiles: undefined }
		]);
	});
});

describe('findRawClaimOption', () => {
	// 3s 4s / 4s 6s / 6s 7s around a discarded 5s: three chows for one discard.
	const raw = [
		{ kind: 'chow', tiles: [80, 84] },
		{ kind: 'chow', tiles: [85, 92] },
		{ kind: 'chow', tiles: [93, 96] },
		{ kind: 'pung', tiles: [88, 89] }
	];

	it('returns the single candidate of a kind', () => {
		expect(findRawClaimOption(raw, { kind: 'pung', tiles: ['5s', '5s'] })).toBe(raw[3]);
	});

	it('disambiguates chows by the tiles they name', () => {
		expect(findRawClaimOption(raw, { kind: 'chow', tiles: ['4s', '6s'] })).toBe(raw[1]);
		expect(findRawClaimOption(raw, { kind: 'chow', tiles: ['6s', '7s'] })).toBe(raw[2]);
	});

	it('is undefined with no raw offer or no match', () => {
		expect(findRawClaimOption(null, { kind: 'pung' })).toBeUndefined();
		expect(findRawClaimOption(raw, { kind: 'win' })).toBeUndefined();
	});
});
