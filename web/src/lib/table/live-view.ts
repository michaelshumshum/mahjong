// Projects a real `ClientGameState` into the `MockGameState`-shaped view model +page.svelte's
// template already renders, so the live path reuses the same render tree instead of a second
// one that could visually drift. `MockGameState` has no room for real tile identity, so
// `LiveTableView.ownHand` carries tile_ids alongside, index-aligned with the view.

import type { ClientGameState, MeldState } from '../game/state';
import { tileIdToCode, type TileCode } from './tile-code';
import type {
	FaanPatternMock,
	HandOutcome,
	MeldKind,
	MockClaimOption,
	MockClaimWindow,
	MockGameState,
	MockHandResult,
	MockMeld,
	MockSeatState,
	Phase,
	Seat,
	Seats,
	Wind,
	WinType
} from './mock-game-state';

export interface LiveOwnHand {
	/** tile_ids for `view.seats[you].concealedHand`, same order, same length. */
	concealedIds: number[];
	/** tile_id for `view.seats[you].drawn`, or `null` when there's no held-apart tile right now. */
	drawnId: number | null;
}

export interface LiveTableView {
	view: MockGameState;
	ownHand: LiveOwnHand;
}

// wire prevailing is the `Wind` enum's *name* (EAST/SOUTH/WEST/NORTH), not the single-letter
// code MockGameState uses everywhere else.
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

export function meldToView(m: MeldState): MockMeld {
	const tiles = m.tiles
		? m.tiles.map(tileIdToCode)
		: // another seat's still-concealed concealed_kong: codes are never read since +page.svelte
			// forces TileFace code={null} for any concealed_kong meld regardless.
			(Array(m.count ?? 0).fill('1m') as TileCode[]);
	return {
		kind: m.kind as MeldKind,
		tiles,
		fromSeat: (m.fromSeat ?? undefined) as Seat | undefined
	};
}

function claimOptionToView(o: Record<string, unknown>): MockClaimOption {
	const tiles = o.tiles as number[] | undefined;
	return {
		kind: o.kind as MockClaimOption['kind'],
		tiles: tiles ? tiles.map(tileIdToCode) : undefined
	};
}

function claimWindowToView(state: ClientGameState): MockClaimWindow | null {
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

/** Anchored deadline, not a countdown carried over the wire -- `state.deadlineTs` is set by
 * `turn` for this seat's AWAIT_ACTION, cleared once this seat acts or the turn moves on. */
function turnDurationMsFromState(state: ClientGameState): number | null {
	return state.turn === state.seat && state.deadlineTs !== null
		? Math.max(0, state.deadlineTs - Date.now())
		: null;
}

function handEndHoldMsFromState(state: ClientGameState): number | null {
	// same anchored-deadline shape as turnDurationMsFromState; null when there's no open hold.
	return state.handEndDeadlineTs !== null
		? Math.max(0, state.handEndDeadlineTs - Date.now())
		: null;
}

function handResultToView(state: ClientGameState): MockHandResult | null {
	const d = state.lastHandEnd;
	if (!d) return null;
	return {
		outcome: d.outcome as HandOutcome,
		winner: d.winner !== null ? (d.winner as Seat) : undefined,
		winType: d.winType !== null ? (d.winType as WinType) : undefined,
		winningHand: d.winningHand ? d.winningHand.map(tileIdToCode) : undefined,
		patterns: d.faanBreakdown
			? Object.entries(d.faanBreakdown).map(([name, faan]): FaanPatternMock => ({ name, faan }))
			: undefined,
		totalFaan: d.faan ?? undefined,
		payments: (d.payments ?? undefined) as MockHandResult['payments']
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

	const seats = [0, 1, 2, 3].map((seat): MockSeatState => {
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
			status: state.seatStatus[seat]
		};
	}) as unknown as Seats;

	const view: MockGameState = {
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
		you
	};

	return { view, ownHand };
}
