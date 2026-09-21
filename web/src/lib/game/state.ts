// Pure client-side game state shape (docs/03-frontend.md §6), built incrementally by
// lib/net/reducer.ts from the real ServerEvent stream (protocol.d.ts). No Svelte/runes here —
// store.svelte.ts wraps this in `$state`; this module stays plain data + a factory so
// lib/net/reducer.spec.ts can test state transitions without a Svelte compile step.
//
// Field names mirror the wire payloads 1:1 (StateSyncPayload above all), camelCased per this
// codebase's hand-written-TS convention — protocol.d.ts itself stays snake_case because it's
// generated straight from the Python wire models (see that file's own header).

export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'resyncing' | 'closed';

/** A live claim offer (from `claim_offer`) or the claim options embedded in a `state_sync`
 * snapshot — the latter has no `window_id` on the wire (StateSyncPayload has no such field),
 * so `windowId` is `null` until the next real `claim_offer` event supplies one. */
export interface ClaimWindowState {
	windowId: number | null;
	options: Record<string, unknown>[];
	deadlineTs: number | null;
}

export interface MeldState {
	kind: string;
	tiles: number[] | null; // null only for another seat's still-concealed concealed_kong
	count: number | null;
	fromSeat: number | null;
}

export interface HandEndState {
	handNo: number;
	outcome: string;
	winner: number | null;
	winType: string | null;
	discarder: number | null;
	faan: number | null;
	faanBreakdown: Record<string, number> | null;
	points: number | null;
	payments: Record<number, number> | null;
	revealed: boolean;
	winningHand: number[] | null;
}

export interface GameEndState {
	handNo: number;
	scores: number[];
}

/** One completed hand, accumulated across a live game (docs/03-frontend.md §6's history note).
 * `hand_end`'s own wire payload has no `dealer`/`prevailing` field — those are captured off
 * `ClientGameState` at the moment the reducer sees the event, since `hand_start` is the only
 * thing that changes them and it always arrives before the matching `hand_end`. */
export interface HandHistoryEntry extends HandEndState {
	dealer: number;
	prevailing: string;
	/** The winning seat's `melds` at the moment `hand_end` fired, snapshotted off
	 * `ClientGameState.melds[winner]` — `null` for a non-win outcome. `state.melds` resets on
	 * the next `hand_start` and the live hand-end overlay reads it straight off `gameState.seats`
	 * (`+page.svelte`'s `FaanBreakdown` invocation), which is fine for the *just-finished* hand
	 * but leaves nothing for a past round once another hand has been dealt. `hand_end`'s own wire
	 * payload has no meld field (only `winning_hand`, the concealed portion) — this is a client-
	 * side capture, not a wire gap, so a game-end summary can still show every past round's full
	 * winning hand (melds + concealed tiles), not just the latest one. */
	winnerMelds: MeldState[] | null;
}

export interface ClientGameState {
	seat: number | null;
	handNo: number;
	prevailing: string;
	dealer: number;
	turn: number;
	phase: string;
	ownHand: number[];
	/** tile_id of the tile this seat drew (or kong-replaced) and hasn't discarded or melded away
	 * yet, so the table can hold it apart from the sorted hand (docs/03-frontend.md's "as in
	 * physical play"). `null` whenever there's nothing to hold apart, including right after
	 * claiming a chow/pung/kong — a claim consumes the discard straight into the exposed meld
	 * (server/mahjong_core/engine.py's claim handling), so unlike a real draw it never leaves a
	 * spare tile sitting in `ownHand` for the client to guess at. */
	drawnTileId: number | null;
	concealedCounts: number[];
	melds: MeldState[][];
	discardPools: number[][];
	flowers: string[][];
	wallRemaining: number;
	seatStatus: string[];
	/** Each seat's resolved guest display name (docs/02-protocol.md §3's `state_sync.names`),
	 * length 4, same indexing as every other per-seat array here. `null` for an `empty` seat;
	 * a real non-empty string (human-chosen or a bot's tier name, e.g. "FaanBot") for any bound
	 * seat. Kept live by `seat_state`'s own `name` field, mirroring how `seatStatus` above is
	 * kept live from the same event. */
	names: (string | null)[];
	/** Whichever seat's `join` was this table's first (docs/02-protocol.md §3's
	 * `state_sync.host_seat`) — `null` before anyone has joined (never actually observable,
	 * since `state_sync` is only ever sent once someone has). Never changes for the life of a
	 * table, so a full resync is the only event that ever needs to set it. */
	hostSeat: number | null;
	scores: number[];
	legalActions: Record<string, unknown>[];
	deadlineTs: number | null;
	claimOffer: ClaimWindowState | null;
	/** The most recent `discard` event seen, kept around only so a live `AWAIT_CLAIMS` window
	 * (whose own `claim_offer` carries no tile/seat, docs/02-protocol.md §3) can show what's
	 * actually being claimed — `turn` still names the discarder for the window's whole lifetime
	 * (no `turn` event fires until it resolves), so this plus `turn` is enough, no dedicated
	 * wire field needed. Not meaningful for a `kong_rob` window; nothing branches on `kind` to
	 * gate that yet (`live-view.ts`'s `claimWindowToView`). */
	lastDiscard: { seat: number; tileId: number } | null;
	lastHandEnd: HandEndState | null;
	/** The hand-end hold's deadline (`hand_end.deadline_ts`): held open until every seat acks
	 * (`hand_end_ack`) or this elapses, whichever first — set by `hand_end`, cleared by the
	 * next `hand_start` (mirrors `lastHandEnd`'s own lifecycle, since both describe the same
	 * held-open round). */
	handEndDeadlineTs: number | null;
	/** Every `hand_end` seen so far this session, oldest first — `lastHandEnd` above only ever
	 * holds the latest one (used for the just-finished-hand overlay), so this is the running
	 * history a score sheet needs. Append-only: never cleared by `hand_start` or `state_sync`
	 * (a redacted snapshot carries no hand history to replace it with — reducer.ts's
	 * `state_sync` case). Starts empty per `GameStore`/session; a reconnect that lands on a
	 * full resync rather than gap-replay can leave it missing hands from before this session
	 * began (`ScoreSheet.svelte`'s `historyComplete` flag exists for exactly that case). */
	handHistory: HandHistoryEntry[];
	gameEnd: GameEndState | null;
	shutdownDeadlineTs: number | null;
}

export function initialClientGameState(): ClientGameState {
	return {
		seat: null,
		handNo: 0,
		prevailing: '',
		dealer: 0,
		turn: 0,
		phase: 'IDLE',
		ownHand: [],
		drawnTileId: null,
		concealedCounts: [0, 0, 0, 0],
		melds: [[], [], [], []],
		discardPools: [[], [], [], []],
		flowers: [[], [], [], []],
		wallRemaining: 0,
		seatStatus: ['disconnected', 'disconnected', 'disconnected', 'disconnected'],
		names: [null, null, null, null],
		hostSeat: null,
		scores: [0, 0, 0, 0],
		legalActions: [],
		deadlineTs: null,
		claimOffer: null,
		lastDiscard: null,
		lastHandEnd: null,
		handEndDeadlineTs: null,
		handHistory: [],
		gameEnd: null,
		shutdownDeadlineTs: null
	};
}
