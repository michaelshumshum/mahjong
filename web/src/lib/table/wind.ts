import type { Seat } from './mock-game-state';
import { getLocale } from '$lib/paraglide/runtime.js';

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

// full-sentence spots need a real word, not a bare glyph -- but in zh-Hant that's WIND_CHAR
// (南風 reads naturally), not WIND_LABEL's English word forced into a Chinese sentence.
export function windWord(wind: WindLetter): string {
	return getLocale() === 'zh-Hant' ? WIND_CHAR[wind] : WIND_LABEL[wind];
}
