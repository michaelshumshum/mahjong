import { describe, it, expect, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', async (importOriginal) => ({
	...(await importOriginal<typeof import('$lib/paraglide/runtime.js')>()),
	getLocale: vi.fn(() => 'en')
}));

import en from '../../../messages/en/table.json';
import zhHant from '../../../messages/zh-Hant/table.json';
import {
	relativeSeat,
	SEAT_POSITIONS,
	SEAT_WINDS,
	seatAtPosition,
	seatFromPosition,
	seatWind,
	seatWindIndex,
	windAtPosition,
	windWord,
	WIND_CHAR
} from './wind';
import { getLocale } from '$lib/paraglide/runtime.js';
import { ALL_SEATS, type Seat } from '$lib/game/types';
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

describe('WIND_CHAR', () => {
	it('covers all four winds', () => {
		for (const w of SEAT_WINDS) {
			expect(WIND_CHAR[w]).toBeTruthy();
		}
	});
});

describe('windWord', () => {
	const keys = { E: 'wind_east', S: 'wind_south', W: 'wind_west', N: 'wind_north' } as const;

	it.each([
		['en', en],
		['zh-Hant', zhHant]
	] as const)('names every wind with its %s message', (locale, messages) => {
		vi.mocked(getLocale).mockReturnValue(locale);
		for (const w of SEAT_WINDS) {
			expect(windWord(w)).toBe(messages[keys[w]]);
		}
	});

	it('uses the Chinese glyph for the zh-Hant locale, not the English word', () => {
		vi.mocked(getLocale).mockReturnValue('zh-Hant');
		expect(windWord('S')).toBe('南');
	});
});

describe('relativeSeat', () => {
	it('returns self when seat equals you', () => {
		expect(relativeSeat(0, 0)).toBe('self');
		expect(relativeSeat(2, 2)).toBe('self');
	});

	it('counts clockwise from you in seat-index space', () => {
		expect(relativeSeat(1, 0)).toBe('right');
		expect(relativeSeat(2, 0)).toBe('across');
		expect(relativeSeat(3, 0)).toBe('left');
	});

	it('wraps around seat 0', () => {
		expect(relativeSeat(0, 1)).toBe('left');
		expect(relativeSeat(0, 3)).toBe('right');
		expect(relativeSeat(2, 3)).toBe('left');
	});
});

describe('seatFromPosition', () => {
	it('inverts relativeSeat for every seat and position', () => {
		for (const you of ALL_SEATS) {
			for (const position of SEAT_POSITIONS) {
				expect(relativeSeat(seatFromPosition(you, position), you)).toBe(position);
			}
		}
	});

	it('wraps around seat 3', () => {
		expect(seatFromPosition(3, 'self')).toBe(3);
		expect(seatFromPosition(3, 'right')).toBe(0);
		expect(seatFromPosition(3, 'across')).toBe(1);
		expect(seatFromPosition(3, 'left')).toBe(2);
	});
});

describe('seatAtPosition', () => {
	const seats = ALL_SEATS.map((seat) => ({ seat }) as SeatView);

	it('finds the seat at a table position relative to you', () => {
		expect(seatAtPosition(seats, 2, 'self').seat).toBe(2);
		expect(seatAtPosition(seats, 2, 'right').seat).toBe(3);
		expect(seatAtPosition(seats, 2, 'across').seat).toBe(0);
		expect(seatAtPosition(seats, 2, 'left').seat).toBe(1);
	});
});

describe('seatWindIndex', () => {
	it('indexes SEAT_WINDS with the same wind seatWind gives', () => {
		for (const dealer of ALL_SEATS) {
			for (const seat of ALL_SEATS) {
				expect(SEAT_WINDS[seatWindIndex(seat, dealer)]).toBe(seatWind(seat, dealer));
			}
		}
	});
});

describe('windAtPosition', () => {
	it('puts your own wind at self and the rest clockwise', () => {
		expect(SEAT_POSITIONS.map((p) => windAtPosition(p, 0))).toEqual(['E', 'S', 'W', 'N']);
		expect(SEAT_POSITIONS.map((p) => windAtPosition(p, 3))).toEqual(['N', 'E', 'S', 'W']);
	});

	it('agrees with seatWind of the seat at that position', () => {
		const you = 1 as Seat;
		const dealer = 2 as Seat;
		for (const position of SEAT_POSITIONS) {
			expect(windAtPosition(position, seatWindIndex(you, dealer))).toBe(
				seatWind(seatFromPosition(you, position), dealer)
			);
		}
	});
});
