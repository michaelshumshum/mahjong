import type { Seat, Wind } from '$lib/game/types';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { SeatView } from './view-types';

export const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const satisfies readonly Wind[];

export const WIND_LABEL: Record<Wind, string> = {
	E: 'East',
	S: 'South',
	W: 'West',
	N: 'North'
};

// table-view wind glyphs; WIND_LABEL stays in use for full-sentence spots where a bare glyph
// would read as unlabelled to a screen reader.
export const WIND_CHAR: Record<Wind, string> = {
	E: '東',
	S: '南',
	W: '西',
	N: '北'
};

// (seat - you) mod 4, clockwise from you: 0 self, 1 right, 2 across, 3 left.
export function relativeSeat(seat: Seat, you: Seat): 0 | 1 | 2 | 3 {
	return ((seat - you + 4) % 4) as 0 | 1 | 2 | 3;
}

export function seatAtPosition(
	seats: readonly SeatView[],
	you: Seat,
	position: 0 | 1 | 2 | 3
): SeatView {
	return seats.find((s) => relativeSeat(s.seat, you) === position)!;
}

// dealer holds East for the current hand, remaining seats follow clockwise in seat-index space.
export function seatWind(seat: Seat, dealer: Seat): Wind {
	return SEAT_WINDS[(seat - dealer + 4) % 4];
}

// full-sentence spots need a real word, not a bare glyph -- but in zh-Hant that's WIND_CHAR
// (南風 reads naturally), not WIND_LABEL's English word forced into a Chinese sentence.
export function windWord(wind: Wind): string {
	return getLocale() === 'zh-Hant' ? WIND_CHAR[wind] : WIND_LABEL[wind];
}
