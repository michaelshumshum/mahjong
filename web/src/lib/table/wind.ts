import { ALL_SEATS, type Seat, type Wind } from '$lib/game/types';
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

// table positions clockwise from you, in seat-index order.
export const SEAT_POSITIONS = ['self', 'right', 'across', 'left'] as const;
export type SeatPosition = (typeof SEAT_POSITIONS)[number];

// (seat - from) wrapped into 0..3: clockwise steps from `from` to `seat`.
function seatOffset(seat: number, from: number): number {
	return (seat - from + ALL_SEATS.length) % ALL_SEATS.length;
}

export function relativeSeat(seat: Seat, you: Seat): SeatPosition {
	return SEAT_POSITIONS[seatOffset(seat, you)];
}

export function seatFromPosition(you: Seat, position: SeatPosition): Seat {
	return ALL_SEATS[seatOffset(you, -SEAT_POSITIONS.indexOf(position))];
}

export function seatAtPosition(
	seats: readonly SeatView[],
	you: Seat,
	position: SeatPosition
): SeatView {
	const seat = seatFromPosition(you, position);
	return seats.find((s) => s.seat === seat)!;
}

// index into SEAT_WINDS: dealer holds East, remaining seats follow clockwise in seat-index space.
export function seatWindIndex(seat: Seat, dealer: Seat): number {
	return seatOffset(seat, dealer);
}

export function seatWind(seat: Seat, dealer: Seat): Wind {
	return SEAT_WINDS[seatWindIndex(seat, dealer)];
}

// the wind at `position` when the viewer's own wind is SEAT_WINDS[selfWindIndex].
export function windAtPosition(position: SeatPosition, selfWindIndex: number): Wind {
	return SEAT_WINDS[seatOffset(selfWindIndex, -SEAT_POSITIONS.indexOf(position))];
}

// full-sentence spots need a real word, not a bare glyph -- but in zh-Hant that's WIND_CHAR
// (南風 reads naturally), not WIND_LABEL's English word forced into a Chinese sentence.
export function windWord(wind: Wind): string {
	return getLocale() === 'zh-Hant' ? WIND_CHAR[wind] : WIND_LABEL[wind];
}
