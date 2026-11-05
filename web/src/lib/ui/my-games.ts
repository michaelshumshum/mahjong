import type { GameMode, MyGameSeat } from '$lib/net/account';
import { m } from '$lib/paraglide/messages.js';

const MODE_LABEL: Record<GameMode, () => string> = {
	practice: m.myGames_modePractice,
	multiplayer: m.myGames_modeMultiplayer
};

/** Null for games saved before modes were recorded. */
export function modeLabel(mode: GameMode | null): string | null {
	return mode ? MODE_LABEL[mode]() : null;
}

export function formatScore(score: number): string {
	return score > 0 ? `+${score}` : String(score);
}

export function formatGameDate(iso: string, locale: string): string {
	return new Date(iso).toLocaleString(locale, { dateStyle: 'medium', timeStyle: 'short' });
}

/** A user or guest seat's name; an unfilled seat saved as a guest has none. */
export function seatName(seat: MyGameSeat): string {
	return seat.name ?? m.myGames_guest();
}
