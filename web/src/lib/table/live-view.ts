// Projects a real `ClientGameState` (docs/03-frontend.md §6, this seat's own redacted view)
// into the `MockGameState`-shaped view model `+page.svelte`'s template already renders
// (mock-game-state.ts). Lets the live path reuse the exact same, already-screenshot-audited
// render tree (TileFace/ClaimButtons/TimerRing/FaanBreakdown/ScoreSheet/...) instead of a
// second parallel one that could visually drift from it -- the alternative this sub-task
// weighed and rejected (docs/03-frontend.md's own "the adapter problem" framing).
//
// The one thing `MockGameState` has no room for is real tile identity: mock tiles are bare
// `TileCode`s with no id, but a live discard/claim/declare intent needs the numeric `tile_id`,
// not just the face. `LiveTableView.ownHand` carries that alongside the view, index-aligned
// with `view.seats[you].concealedHand`/`.drawn`, for `+page.svelte`'s interactive hand tiles.

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

// `state.prevailing`/`hand_start.prevailing` are the wire's `Wind` enum *name*
// (`app/views.py`/`app/room.py`: `state.prevailing.name` -- IntEnum members EAST=0..NORTH=3),
// not the single-letter code (`'E'|'S'|'W'|'N'`) `WIND_LABEL`/`MockGameState` use everywhere
// else. Only found by actually running a live hand end to end -- every mock scenario already
// hardcodes the single-letter form, so nothing else exercises this mismatch.
const WIRE_WIND_TO_CODE: Record<string, Wind> = { EAST: 'E', SOUTH: 'S', WEST: 'W', NORTH: 'N' };

/** Exported for `+page.svelte`'s `scoreHands` mapping — `ClientGameState.handHistory` entries
 * carry the same wire-form `prevailing` string this converts for the live view's own field. */
export function wireWindToCode(wind: string): Wind {
	return WIRE_WIND_TO_CODE[wind] ?? (wind as Wind);
}

function sortByTileType(ids: readonly number[]): number[] {
	// TileType order (0..33: m1..m9, p1..p9, s1..s9, z1..z7, tiles.py) is exactly `tile_id // 4`
	// -- the same order a sorted hand should read in (docs/03-frontend.md §3's "13 faces,
	// sorted"), so no separate comparator over TileCode is needed.
	return ids.slice().sort((a, b) => Math.floor(a / 4) - Math.floor(b / 4));
}

/** `state.ownHand` is a flat array with no "which one is drawn" marker; the reducer always
 * appends a fresh draw to the end (lib/net/reducer.ts's `draw`/`kong_replace` cases), so the
 * last element is the held-apart tile for exactly as long as this seat has one -- i.e. while
 * it's this seat's turn with a legal `discard` still available (once discarded, or once melded,
 * the reducer has already removed the specific tile_id, drawn or not, from `ownHand`). */
function splitOwnHand(state: ClientGameState): LiveOwnHand {
	if (state.seat === null) return { concealedIds: [], drawnId: null };
	const canDiscard =
		state.turn === state.seat && state.legalActions.some((a) => a.kind === 'discard');
	if (!canDiscard) return { concealedIds: sortByTileType(state.ownHand), drawnId: null };
	const drawnId = state.ownHand[state.ownHand.length - 1] ?? null;
	return { concealedIds: sortByTileType(state.ownHand.slice(0, -1)), drawnId };
}

function meldToView(m: MeldState): MockMeld {
	const tiles = m.tiles
		? m.tiles.map(tileIdToCode)
		: // another seat's still-concealed concealed_kong: no real tiles to show yet (redacted to
			// `count` only, docs/02-protocol.md §3) -- the codes themselves are never read, since
			// +page.svelte forces `TileFace code={null}` for any `concealed_kong` meld regardless.
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
	// a `window_id`-less offer only ever comes from a state_sync snapshot embedding
	// `claim_options` with no live `claim_offer` behind it yet (state.ts's `ClaimWindowState`
	// doc comment) -- there's no real id to claim against, so don't offer buttons for it; the
	// real `claim_offer` event that follows will carry one.
	if (!offer || offer.windowId === null) return null;
	return {
		windowId: offer.windowId,
		// `kind`/`sourceSeat`/`tile` are MockClaimWindow fields the template never actually reads
		// (only `.yourOptions` and `.durationMs` are) -- real values live server-side and aren't
		// on the wire here, so these are inert placeholders, not a redaction gap.
		kind: 'discard',
		sourceSeat: state.turn as Seat,
		tile: '1m',
		durationMs: offer.deadlineTs !== null ? Math.max(0, offer.deadlineTs - Date.now()) : 0,
		yourOptions: offer.options.map(claimOptionToView)
	};
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

/** `null` before this seat is known (pre-join/pre-`state_sync`) -- there's no `you` to build a
 * seat-relative view around yet. */
export function viewFromClientState(state: ClientGameState): LiveTableView | null {
	if (state.seat === null) return null;
	const you = state.seat as Seat;
	const ownHand = splitOwnHand(state);
	const concealedCodes = ownHand.concealedIds.map(tileIdToCode);
	const drawnCode = ownHand.drawnId !== null ? tileIdToCode(ownHand.drawnId) : null;

	const seats = [0, 1, 2, 3].map((seat): MockSeatState => {
		const isYou = seat === you;
		return {
			seat: seat as Seat,
			name: isYou ? 'You' : `Seat ${seat}`,
			concealedCount: state.concealedCounts[seat],
			concealedHand: isYou ? concealedCodes : undefined,
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
		you
	};

	return { view, ownHand };
}
