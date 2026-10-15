// domain types shared by table, win/score screens and mock fixtures. hand-written: the wire
// types seats as `number` and meld/claim kinds as `string`, nothing narrower to derive from.

import type { TileCode } from '$lib/table/tile-code';

export type Seat = 0 | 1 | 2 | 3;
export type Wind = 'E' | 'S' | 'W' | 'N';

// mirrors state.Phase; AWAIT_KONG_ROB/SCORING/GAME_OVER included for completeness though no
// mock scenario uses them yet.
export type Phase =
	| 'AWAIT_DRAW'
	| 'AWAIT_ACTION'
	| 'AWAIT_CLAIMS'
	| 'AWAIT_KONG_ROB'
	| 'SCORING'
	| 'HAND_OVER'
	| 'GAME_OVER';

// mirrors melds.MeldKind, minus PAIR (SeatState.melds never holds a bare pair).
export type MeldKind = 'chow' | 'pung' | 'exposed_kong' | 'concealed_kong' | 'added_kong';

export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

// mirrors the wire claim{window_id, choice, tiles?} shape; `tiles` only disambiguates chow.
// no `window_id` here -- pure presentation, wiring to a real window is the caller's job.
export interface ClaimOption {
	kind: ClaimKind;
	tiles?: TileCode[];
}

export type HandOutcome = 'win' | 'exhaustive_draw';
export type WinType = 'self_draw' | 'discard' | 'kong_rob';

export interface FaanPattern {
	name: string;
	faan: number;
}

// kind/tiles only -- what the win and score screens render.
export interface WinningMeld {
	kind: MeldKind;
	tiles: TileCode[];
}

// mirrors hand_end.payments (docs/protocol.md §3): per-seat point delta for one hand. `Partial`
// because a seat with nothing to pay or collect has no entry rather than an explicit 0.
export type Payments = Partial<Record<Seat, number>>;

export interface SeatInfo {
	seat: Seat;
	name: string;
}

// mirrors score.totals: authoritative running total per seat, last received from the server.
// kept as its own ScoreSheet prop rather than derived only from `hands` -- see `historyComplete`.
export type Totals = Record<Seat, number>;

// one already-finished hand.
export interface HandRecord {
	handNo: number;
	dealer: Seat;
	prevailing: Wind;
	deltas: Payments;
	/** Optional per-round detail -- present, this round's row becomes expandable, revealing
	 * the winning hand or a plain draw note inline via `WinningHand`. */
	result?: RoundResult;
}

export interface RoundResult {
	outcome: HandOutcome;
	winner?: Seat;
	winningHand?: TileCode[];
	melds?: WinningMeld[];
	patterns?: FaanPattern[];
	totalFaan?: number;
	payments?: Payments;
}

// `game_end` only ever carries {hand_no, scores} -- absolute totals, no ranking baked in.
// `standings` (ranked order, index 0 = 1st) is left for a caller to fill in when it has one.
export interface Standing {
	seat: Seat;
	total: number;
}
