// projects a real `ClientGameState` into the `TableView`-shaped view model so live and mock
// share one render tree. `LiveTableView.ownHand` carries real tile_ids alongside, index-aligned with the view.

import type { ClientGameState, MeldState } from '../game/state';
import { tileIdToCode, type TileCode } from './tile-code';
import type {
	ClaimOption,
	FaanPattern,
	HandOutcome,
	MeldKind,
	Phase,
	Seat,
	Wind,
	WinType
} from '$lib/game/types';
import type {
	ClaimWindowView,
	TableView,
	HandResultView,
	MeldView,
	SeatView,
	Seats
} from './view-types';

export interface LiveOwnHand {
	/** tile_ids for `view.seats[you].concealedHand`, same order, same length. */
	concealedIds: number[];
	/** tile_id for `view.seats[you].drawn`, or `null` when there's no held-apart tile right now. */
	drawnId: number | null;
}

export interface LiveTableView {
	view: TableView;
	ownHand: LiveOwnHand;
}

// wire prevailing is the `Wind` enum's *name* (EAST/SOUTH/WEST/NORTH), not the single-letter
// code TableView uses everywhere else.
const WIRE_WIND_TO_CODE: Record<string, Wind> = { EAST: 'E', SOUTH: 'S', WEST: 'W', NORTH: 'N' };

export function wireWindToCode(wind: string): Wind {
	return WIRE_WIND_TO_CODE[wind] ?? (wind as Wind);
}

function sortByTileType(ids: readonly number[]): number[] {
	// TileType order (0..33) is exactly tile_id // 4 -- no separate TileCode comparator needed.
	return ids.slice().sort((a, b) => Math.floor(a / 4) - Math.floor(b / 4));
}

function splitOwnHand(state: ClientGameState): LiveOwnHand {
	if (state.seat === null) return { concealedIds: [], drawnId: null };
	const canDiscard =
		state.turn === state.seat && state.legalActions.some((a) => a.kind === 'discard');
	if (!canDiscard || state.drawnTileId === null) {
		return { concealedIds: sortByTileType(state.ownHand), drawnId: null };
	}
	return {
		concealedIds: sortByTileType(state.ownHand.filter((id) => id !== state.drawnTileId)),
		drawnId: state.drawnTileId
	};
}

export function meldToView(m: MeldState): MeldView {
	return {
		kind: m.kind as MeldKind,
		tiles: m.tiles.map(tileIdToCode),
		fromSeat: (m.fromSeat ?? undefined) as Seat | undefined
	};
}

function claimOptionToView(o: Record<string, unknown>): ClaimOption {
	const tiles = o.tiles as number[] | undefined;
	return {
		kind: o.kind as ClaimOption['kind'],
		tiles: tiles ? tiles.map(tileIdToCode) : undefined
	};
}

function claimWindowToView(state: ClientGameState): ClaimWindowView | null {
	const offer = state.claimOffer;
	// a window_id-less offer comes from a state_sync snapshot with no live claim_offer yet --
	// no real id to claim against, so don't offer buttons; the real claim_offer will carry one.
	if (!offer || offer.windowId === null) return null;
	// `kind` stays a placeholder -- the wire never says discard vs kong_rob and nothing
	// downstream branches on it. `sourceSeat`/`tile` are real, from `state.lastDiscard`.
	return {
		windowId: offer.windowId,
		kind: 'discard',
		sourceSeat: state.turn as Seat,
		tile: state.lastDiscard ? tileIdToCode(state.lastDiscard.tileId) : '1m',
		durationMs: offer.deadlineTs !== null ? Math.max(0, offer.deadlineTs - Date.now()) : 0,
		yourOptions: offer.options.map(claimOptionToView)
	};
}

/** Anchored on any seat's `turn` deadline. The phase guard drops a `state_sync`'s own
 * claim/hand-end deadline, which isn't the acting seat's. */
function turnDurationMsFromState(state: ClientGameState): number | null {
	return state.phase === 'AWAIT_ACTION' && state.deadlineTs !== null
		? Math.max(0, state.deadlineTs - Date.now())
		: null;
}

/** `state.lastDiscard.tileId` -> this seat's position in its own (unclaimed-filtered) pool, for
 * `CenterDiscardPool`'s marker. `null` once claimed (the tile no longer appears in the pool). */
function lastDiscardToView(state: ClientGameState): { seat: Seat; index: number } | null {
	const d = state.lastDiscard;
	if (!d) return null;
	const index = state.discardPools[d.seat].indexOf(d.tileId);
	return index === -1 ? null : { seat: d.seat as Seat, index };
}

function handEndHoldMsFromState(state: ClientGameState): number | null {
	// same anchored-deadline shape as turnDurationMsFromState; null when there's no open hold.
	return state.handEndDeadlineTs !== null
		? Math.max(0, state.handEndDeadlineTs - Date.now())
		: null;
}

function handResultToView(state: ClientGameState): HandResultView | null {
	const d = state.lastHandEnd;
	if (!d) return null;
	return {
		outcome: d.outcome as HandOutcome,
		winner: d.winner !== null ? (d.winner as Seat) : undefined,
		winType: d.winType !== null ? (d.winType as WinType) : undefined,
		winningHand: d.winningHand ? d.winningHand.map(tileIdToCode) : undefined,
		patterns: d.faanBreakdown
			? Object.entries(d.faanBreakdown).map(([name, faan]): FaanPattern => ({
					name,
					faan
				}))
			: undefined,
		totalFaan: d.faan ?? undefined,
		payments: (d.payments ?? undefined) as HandResultView['payments'],
		fairness: d.fairness ?? undefined
	};
}

/** `null` before this seat is known. A spectator (`seat === null`) passes `spectateFrom` instead
 * -- no concealed tiles unless the table shows spectators every hand (`state.hands`). */
export function viewFromClientState(
	state: ClientGameState,
	spectateFrom: Seat | null = null
): LiveTableView | null {
	const you = (state.seat ?? spectateFrom) as Seat | null;
	if (you === null) return null;
	const ownHand = splitOwnHand(state);
	const concealedCodes = ownHand.concealedIds.map(tileIdToCode);
	const drawnCode = ownHand.drawnId !== null ? tileIdToCode(ownHand.drawnId) : null;

	const seats = [0, 1, 2, 3].map((seat): SeatView => {
		const isYou = state.seat !== null && seat === you;
		const openHand = state.hands?.[seat];
		return {
			seat: seat as Seat,
			// isYou/Seat N fallback only covers the moment before a real name has arrived.
			name: state.names[seat] ?? (isYou ? 'You' : `Seat ${seat}`),
			concealedCount: state.concealedCounts[seat],
			concealedHand: isYou
				? concealedCodes
				: openHand
					? sortByTileType(openHand).map(tileIdToCode)
					: undefined,
			drawn: isYou ? drawnCode : undefined,
			melds: state.melds[seat].map(meldToView),
			discards: state.discardPools[seat]
				.filter((id): id is number => id !== undefined)
				.map(tileIdToCode),
			flowers: state.flowers[seat] as TileCode[],
			score: state.scores[seat],
			status: state.seatStatus[seat],
			botLevel: state.botLevels[seat]
		};
	}) as unknown as Seats;

	const view: TableView = {
		phase: state.phase as Phase,
		turn: state.turn as Seat,
		dealer: state.dealer as Seat,
		prevailing: wireWindToCode(state.prevailing),
		handNo: state.handNo,
		wallCount: state.wallRemaining,
		seats,
		claimWindow: claimWindowToView(state),
		handResult: handResultToView(state),
		handEndHoldMs: handEndHoldMsFromState(state),
		turnDurationMs: turnDurationMsFromState(state),
		you,
		lastDiscard: lastDiscardToView(state)
	};

	return { view, ownHand };
}
