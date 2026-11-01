import type { Seat } from '$lib/game/types';
import { initialClientGameState, type ClientGameState } from '$lib/game/state';
import { m } from '$lib/paraglide/messages.js';
import { reduce } from '$lib/net/reducer';
import { seatWind, windWord } from '$lib/table/wind';
import type { Lesson } from './generated/lessons';

/** The snapshot as a live resync would apply it. A claim puzzle is answered in the answer card,
 * so its offer is dropped; only its claimed tile keeps the last-discard mark. */
export function puzzleState(lesson: Lesson): ClientGameState {
	const state = reduce(initialClientGameState(), lesson.snapshot);
	return withSeatNames({
		...state,
		claimOffer: null,
		lastDiscard: state.claimOffer ? state.lastDiscard : null
	});
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
