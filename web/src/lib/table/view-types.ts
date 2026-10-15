// table view model, single-seat redacted; rendered from both MOCK_SCENARIOS and the live store
// (live-view.ts) so they share one render tree.

import type { FairnessState } from '$lib/game/state';
import type {
	ClaimOption,
	FaanPattern,
	HandOutcome,
	MeldKind,
	Payments,
	Phase,
	Seat,
	Standing,
	Wind,
	WinType
} from '$lib/game/types';
import type { BotTier } from '$lib/net/protocol';
import type { TileCode } from './tile-code';

export interface MeldView {
	kind: MeldKind;
	// real tile identities always; a concealed_kong shows its end tiles as backs (meld-face.ts).
	tiles: TileCode[];
	fromSeat?: Seat; // undefined for concealed_kong/added_kong, mirrors Meld.from_seat = None
}

// mirrors state.SeatState, redacted: `concealedHand` is only populated for the "you" seat;
// every other seat gets `concealedCount` only.
export interface SeatView {
	seat: Seat;
	name: string;
	concealedCount: number;
	concealedHand?: TileCode[]; // the "you" seat, or every seat for an open-hands spectator
	drawn?: TileCode | null; // held-apart 14th tile; "you" seat only, real events redact this too
	melds: MeldView[];
	discards: TileCode[];
	flowers: TileCode[];
	score: number;
	// wire seat_status -- optional since no mock fixture sets it (no bot concept in mocks);
	// live-view.ts populates it from ClientGameState.seatStatus.
	status?: string;
	botLevel?: BotTier | null;
}

export type Seats = [SeatView, SeatView, SeatView, SeatView];

// mirrors state.ClaimWindow, redacted to this seat's own offer only. `null` (not an empty
// array) means "not offered".
export interface ClaimWindowView {
	windowId: number;
	kind: 'discard' | 'kong_rob';
	sourceSeat: Seat;
	tile: TileCode;
	durationMs: number;
	yourOptions: ClaimOption[] | null;
}

// mirrors state.HandResult plus FaanBreakdown.svelte's payments shape -- only populated for
// outcome 'win'; exhaustive_draw carries no winner/patterns/payments.
export interface HandResultView {
	outcome: HandOutcome;
	winner?: Seat;
	winType?: WinType;
	winningHand?: TileCode[];
	patterns?: FaanPattern[];
	totalFaan?: number;
	payments?: Payments;
	fairness?: FairnessState;
}

// mirrors types.ts's `RoundResult`, kept as a separate parallel type since its melds keep
// MeldView's `fromSeat`.
export interface RoundResultView {
	outcome: HandOutcome;
	winner?: Seat;
	winningHand?: TileCode[];
	melds?: MeldView[];
	patterns?: FaanPattern[];
	totalFaan?: number;
	payments?: Payments;
}

// mirrors types.ts's `HandRecord`, minus the seat-name resolution ScoreSheet does itself.
export interface ScoreRoundView {
	handNo: number;
	dealer: Seat;
	prevailing: Wind;
	deltas: Payments;
	result?: RoundResultView;
}

// a completed game's full history + final ranking -- present only on the one scenario that's
// actually reached `game_end`.
export interface GameEndSummaryView {
	rounds: ScoreRoundView[];
	standings: Standing[];
}

// mirrors state.GameState, redacted to one seat's point of view. `you` is always 0 in the
// mock scenarios but kept as a field since the real per-seat stream will vary it.
export interface TableView {
	phase: Phase;
	turn: Seat;
	dealer: Seat;
	prevailing: Wind;
	handNo: number;
	wallCount: number;
	seats: Seats;
	claimWindow: ClaimWindowView | null;
	handResult: HandResultView | null;
	// hand-end hold's remaining time; `null` when `handResult` is (no hold to show).
	handEndHoldMs: number | null;
	// the acting seat's AWAIT_ACTION deadline (any seat); `null` outside AWAIT_ACTION.
	turnDurationMs: number | null;
	you: Seat;
	/** Set only on the one scenario that's actually reached `game_end` -- lets `GameEndScreen`
	 * be reachable/screenshot-able with no backend running. */
	gameEnd?: GameEndSummaryView;
	/** Most recent unclaimed discard, by its index in that seat's own `discards` array -- the
	 * pool marker (CenterDiscardPool). `undefined`/`null` in every static mock scenario. */
	lastDiscard?: { seat: Seat; index: number } | null;
	/** This table's `RuleSet.min_faan`, for CenterHub's chip. Optional since no scenario
	 * sets it -- callers fall back to the server default (3, `lib/net/ruleset.ts`). */
	minFaan?: number;
}

// your own hand, as YourSeatRegion renders it (live tiles carry their tile_id).
export interface OwnHandTile {
	key: string;
	code: TileCode;
	tileId: number | null;
	drawn: boolean;
}

export interface DeclareOption {
	key: string;
	label: string;
	tiles?: TileCode[];
	onClick: () => void;
	// a self-drawn win: the one declare option worth making unmissable (P1.10) -- kongs stay
	// secondary buttons alongside it, never competing for the eye.
	hero?: boolean;
}
