import { ALL_SEATS, type Seat, type Wind } from '$lib/game/types';
import { m } from '$lib/paraglide/messages.js';
import type { SeatView } from './view-types';

export const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const satisfies readonly Wind[];

const WIND_WORD: Record<Wind, () => string> = {
	E: m.wind_east,
	S: m.wind_south,
	W: m.wind_west,
	N: m.wind_north
};

// table-view wind glyphs, in every locale; windWord() is for full-sentence spots, where a bare
// glyph would read as unlabelled to a screen reader.
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

// the wind's localized word (East / 東), for full sentences and aria labels.
export function windWord(wind: Wind): string {
	return WIND_WORD[wind]();
}
