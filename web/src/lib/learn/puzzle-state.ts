import type { Seat } from '$lib/game/types';
import { initialClientGameState, type ClientGameState } from '$lib/game/state';
import { m } from '$lib/paraglide/messages.js';
import { reduce } from '$lib/net/reducer';
import { seatWind, windWord } from '$lib/table/wind';
import type { Lesson } from './generated/lessons';

/** The lesson's snapshot as the same full replace a live resync is, with no socket. */
export function puzzleState(lesson: Lesson): ClientGameState {
	return withSeatNames(reduce(initialClientGameState(), lesson.snapshot));
}

/** A lesson snapshot has no players to name: you, and each opponent by seat wind, as the
 * prompts and tips name them. */
export function withSeatNames(state: ClientGameState): ClientGameState {
	const names = state.names.map((name, seat) =>
		seat === state.seat
			? m.learn_seatYou()
			: (name ?? m.learn_seatWind({ wind: windWord(seatWind(seat as Seat, state.dealer as Seat)) }))
	);
	return { ...state, names };
}
