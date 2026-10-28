import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: vi.fn(() => 'en') }));

import { relativeSeat, seatAtPosition, seatWind, windWord, WIND_LABEL, WIND_CHAR } from './wind';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { Seat } from '$lib/game/types';
import type { SeatView } from './view-types';

describe('seatWind', () => {
	it('gives the dealer East', () => {
		expect(seatWind(2 as Seat, 2 as Seat)).toBe('E');
	});

	it('follows the dealer clockwise in seat-index space', () => {
		expect(seatWind(3 as Seat, 2 as Seat)).toBe('S');
		expect(seatWind(0 as Seat, 2 as Seat)).toBe('W');
		expect(seatWind(1 as Seat, 2 as Seat)).toBe('N');
	});

	it('wraps around seat 0', () => {
		expect(seatWind(0 as Seat, 0 as Seat)).toBe('E');
		expect(seatWind(3 as Seat, 0 as Seat)).toBe('N');
	});
});

describe('WIND_LABEL / WIND_CHAR', () => {
	it('cover all four winds', () => {
		for (const w of ['E', 'S', 'W', 'N'] as const) {
			expect(WIND_LABEL[w]).toBeTruthy();
			expect(WIND_CHAR[w]).toBeTruthy();
		}
	});
});

describe('windWord', () => {
	it('uses the English word for the en locale', () => {
		vi.mocked(getLocale).mockReturnValue('en');
		expect(windWord('S')).toBe('South');
	});

	it('uses the Chinese glyph for the zh-Hant locale, not the English word', () => {
		vi.mocked(getLocale).mockReturnValue('zh-Hant');
		expect(windWord('S')).toBe('南');
	});
});

describe('relativeSeat', () => {
	it('returns 0 when seat equals you', () => {
		expect(relativeSeat(0, 0)).toBe(0);
		expect(relativeSeat(2, 2)).toBe(0);
	});

	it('counts clockwise from you in seat-index space', () => {
		expect(relativeSeat(1, 0)).toBe(1);
		expect(relativeSeat(2, 0)).toBe(2);
		expect(relativeSeat(3, 0)).toBe(3);
	});

	it('wraps around seat 0', () => {
		expect(relativeSeat(0, 1)).toBe(3);
		expect(relativeSeat(0, 3)).toBe(1);
		expect(relativeSeat(2, 3)).toBe(3);
	});
});

describe('seatAtPosition', () => {
	const seats = ([0, 1, 2, 3] as const).map((seat) => ({ seat }) as SeatView);

	it('finds the seat at a table position relative to you', () => {
		expect(seatAtPosition(seats, 2, 0).seat).toBe(2);
		expect(seatAtPosition(seats, 2, 1).seat).toBe(3);
		expect(seatAtPosition(seats, 2, 2).seat).toBe(0);
		expect(seatAtPosition(seats, 2, 3).seat).toBe(1);
	});
});
