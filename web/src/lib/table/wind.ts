import type { Seat } from './mock-game-state';

export const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const;
export type WindLetter = (typeof SEAT_WINDS)[number];

export const WIND_LABEL: Record<WindLetter, string> = {
	E: 'East',
	S: 'South',
	W: 'West',
	N: 'North'
};

// table-view wind glyphs; WIND_LABEL stays in use for full-sentence spots where a bare glyph
// would read as unlabelled to a screen reader.
export const WIND_CHAR: Record<WindLetter, string> = { E: '東', S: '南', W: '西', N: '北' };

// dealer holds East for the current hand, remaining seats follow clockwise in seat-index space.
export function seatWind(seat: Seat, dealer: Seat): WindLetter {
	return SEAT_WINDS[(seat - dealer + 4) % 4];
}
