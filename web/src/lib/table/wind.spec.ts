import { describe, it, expect } from 'vitest';
import { seatWind, WIND_LABEL, WIND_CHAR } from './wind';
import type { Seat } from './mock-game-state';

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
