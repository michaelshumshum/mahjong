// mock GameState-shaped fixture mirroring mahjong_core's GameState/SeatState/Phase, camelCased and
// pre-redacted for a single seat's view. Opponent hands are plain counts; TileCodes only where the wire would reveal them.

import type { TileCode } from './tile-code';

export type Seat = 0 | 1 | 2 | 3;
export type Wind = 'E' | 'S' | 'W' | 'N';

// mirrors state.Phase; AWAIT_KONG_ROB/SCORING/GAME_OVER included for completeness though no
// mock scenario below uses them yet.
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

export interface MockMeld {
	kind: MeldKind;
	// real tile identities always, even for concealed_kong -- TileFace renders it as backs.
	tiles: TileCode[];
	fromSeat?: Seat; // undefined for concealed_kong/added_kong, mirrors Meld.from_seat = None
}

// mirrors state.SeatState, redacted: `concealedHand` is only populated for the "you" seat;
// every other seat gets `concealedCount` only.
export interface MockSeatState {
	seat: Seat;
	name: string;
	concealedCount: number;
	concealedHand?: TileCode[]; // the "you" seat, or every seat for an open-hands spectator
	drawn?: TileCode | null; // held-apart 14th tile; "you" seat only, real events redact this too
	melds: MockMeld[];
	discards: TileCode[];
	flowers: TileCode[];
	score: number;
	// wire seat_status -- optional since no mock fixture sets it (no bot concept in mocks);
	// live-view.ts populates it from ClientGameState.seatStatus.
	status?: string;
}

export type Seats = [MockSeatState, MockSeatState, MockSeatState, MockSeatState];

export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

export interface MockClaimOption {
	kind: ClaimKind;
	tiles?: TileCode[];
}

// mirrors state.ClaimWindow, redacted to this seat's own offer only. `null` (not an empty
// array) means "not offered".
export interface MockClaimWindow {
	windowId: number;
	kind: 'discard' | 'kong_rob';
	sourceSeat: Seat;
	tile: TileCode;
	durationMs: number;
	yourOptions: MockClaimOption[] | null;
}

export type HandOutcome = 'win' | 'exhaustive_draw';
export type WinType = 'self_draw' | 'discard' | 'kong_rob';

export interface FaanPatternMock {
	name: string;
	faan: number;
}

// mirrors state.HandResult plus FaanBreakdown.svelte's payments shape -- only populated for
// outcome 'win'; exhaustive_draw carries no winner/patterns/payments.
export interface MockHandResult {
	outcome: HandOutcome;
	winner?: Seat;
	winType?: WinType;
	winningHand?: TileCode[];
	patterns?: FaanPatternMock[];
	totalFaan?: number;
	payments?: Partial<Record<Seat, number>>;
}

// mirrors ScoreSheet.svelte's `RoundResult`, kept as a separate parallel type since this module
// has no UI-component dependency -- writes `TileCode`s directly, same as `MockHandResult`.
export interface MockRoundResult {
	outcome: HandOutcome;
	winner?: Seat;
	winningHand?: TileCode[];
	melds?: MockMeld[];
	patterns?: FaanPatternMock[];
	totalFaan?: number;
	payments?: Partial<Record<Seat, number>>;
}

// mirrors ScoreSheet.svelte's `HandRecord`, minus the seat-name resolution ScoreSheet does itself.
export interface MockScoreRound {
	handNo: number;
	dealer: Seat;
	prevailing: Wind;
	deltas: Partial<Record<Seat, number>>;
	result?: MockRoundResult;
}

// a completed game's full history + final ranking -- present only on the one scenario that's
// actually reached `game_end` (below).
export interface MockGameEndSummary {
	rounds: MockScoreRound[];
	standings: { seat: Seat; total: number }[];
}

// mirrors state.GameState, redacted to one seat's point of view. `you` is always 0 in the
// scenarios below but kept as a field since the real per-seat stream will vary it.
export interface MockGameState {
	phase: Phase;
	turn: Seat;
	dealer: Seat;
	prevailing: Wind;
	handNo: number;
	wallCount: number;
	seats: Seats;
	claimWindow: MockClaimWindow | null;
	handResult: MockHandResult | null;
	// hand-end hold's remaining time; `null` when `handResult` is (no hold to show).
	handEndHoldMs: number | null;
	// the acting seat's AWAIT_ACTION deadline (any seat); `null` outside AWAIT_ACTION.
	turnDurationMs: number | null;
	you: Seat;
	/** Set only on the one scenario that's actually reached `game_end` -- lets `GameEndScreen`
	 * be reachable/screenshot-able with no backend running. */
	gameEnd?: MockGameEndSummary;
	/** Most recent unclaimed discard, by its index in that seat's own `discards` array -- the
	 * pool marker (CenterDiscardPool). `undefined`/`null` in every static mock scenario. */
	lastDiscard?: { seat: Seat; index: number } | null;
	/** This table's `RuleSet.min_faan`, for CenterHub's chip. Optional since no scenario below
	 * sets it -- callers fall back to the server default (3, `lib/net/ruleset.ts`). */
	minFaan?: number;
}

// (seat - you) mod 4, clockwise from you: 0 self, 1 right, 2 across, 3 left.
export function relativeSeat(seat: Seat, you: Seat): 0 | 1 | 2 | 3 {
	return ((seat - you + 4) % 4) as 0 | 1 | 2 | 3;
}

const SEAT_NAMES = ['You', 'Bob', 'Carol', 'Dave'];

function emptySeat(seat: Seat, overrides: Partial<MockSeatState> = {}): MockSeatState {
	return {
		seat,
		name: SEAT_NAMES[seat],
		concealedCount: 13,
		melds: [],
		discards: [],
		flowers: [],
		score: 0,
		...overrides
	};
}

// Scenario 1: your turn to discard, holding a drawn tile. No claim window, no hand result.
export const yourTurnToDiscard: MockGameState = {
	phase: 'AWAIT_ACTION',
	turn: 0,
	dealer: 0,
	prevailing: 'E',
	handNo: 3,
	wallCount: 68,
	you: 0,
	claimWindow: null,
	handResult: null,
	handEndHoldMs: null,
	turnDurationMs: 15000,
	lastDiscard: { seat: 2, index: 4 },
	seats: [
		emptySeat(0, {
			concealedHand: ['1m', '2m', '3m', '4p', '5p', '6p', '2s', '3s', '4s', 'z5', 'z5', 'z5', '9s'],
			drawn: '9m',
			flowers: ['f1'],
			discards: ['1s', '9p', 'z2'],
			score: 40
		}),
		emptySeat(1, {
			concealedCount: 13,
			melds: [{ kind: 'pung', tiles: ['z1', 'z1', 'z1'], fromSeat: 3 }],
			discards: ['2p', '3p', '7s', 'z4'],
			flowers: ['f3'],
			score: -20
		}),
		emptySeat(2, {
			concealedCount: 13,
			discards: ['9m', '1p', '5s', '6s', 'z6'],
			score: 10
		}),
		emptySeat(3, {
			concealedCount: 10,
			melds: [
				{ kind: 'chow', tiles: ['4m', '5m', '6m'], fromSeat: 2 },
				{ kind: 'exposed_kong', tiles: ['z7', 'z7', 'z7', 'z7'], fromSeat: 1 }
			],
			discards: ['8p', '2m'],
			score: -30
		})
	]
};

// Scenario 2: seat 1 just discarded a tile you (seat 0) can pung or win on. Turn still shows
// the last actor (seat 1) since it doesn't advance until the window resolves.
export const claimWindowOpenForYou: MockGameState = {
	phase: 'AWAIT_CLAIMS',
	turn: 1,
	dealer: 2,
	prevailing: 'E',
	handNo: 5,
	wallCount: 41,
	you: 0,
	handResult: null,
	handEndHoldMs: null,
	turnDurationMs: null,
	claimWindow: {
		windowId: 12,
		kind: 'discard',
		sourceSeat: 1,
		tile: 'z5',
		durationMs: 5000,
		yourOptions: [{ kind: 'pung', tiles: ['z5', 'z5'] }, { kind: 'win' }, { kind: 'pass' }]
	},
	seats: [
		emptySeat(0, {
			concealedHand: ['2m', '3m', '4m', '4p', '5p', '6p', '7p', '8p', '9p', 'z5', 'z5', '3s', '3s'],
			drawn: null,
			discards: ['1s', '9p'],
			score: 55
		}),
		emptySeat(1, {
			concealedCount: 12,
			discards: ['2p', '3p', '7s', 'z4', 'z5'],
			score: -15
		}),
		emptySeat(2, {
			concealedCount: 13,
			melds: [{ kind: 'pung', tiles: ['z3', 'z3', 'z3'], fromSeat: 0 }],
			discards: ['9m', '1p'],
			score: -10
		}),
		emptySeat(3, {
			concealedCount: 13,
			discards: ['8p', '2m', '6s'],
			score: -30
		})
	]
};

// Scenario 3: seat 2 self-drew a Half Flush hand; payments spread across all three other seats.
export const handJustEnded: MockGameState = {
	phase: 'HAND_OVER',
	turn: 2,
	dealer: 2,
	prevailing: 'E',
	handNo: 5,
	wallCount: 12,
	you: 0,
	claimWindow: null,
	seats: [
		emptySeat(0, {
			concealedCount: 13,
			discards: ['1s', '9p', 'z2', '4m'],
			score: 40 - 16
		}),
		emptySeat(1, {
			concealedCount: 13,
			discards: ['2p', '3p', '7s'],
			score: -20 - 16
		}),
		emptySeat(2, {
			concealedCount: 0,
			melds: [{ kind: 'chow', tiles: ['2s', '3s', '4s'], fromSeat: 1 }],
			discards: ['9m', '1p', '5s'],
			flowers: ['f2'],
			score: 10 + 48
		}),
		emptySeat(3, {
			concealedCount: 13,
			discards: ['8p', '2m'],
			score: -30 - 16
		})
	],
	handResult: {
		outcome: 'win',
		winner: 2,
		winType: 'self_draw',
		// concealed portion only -- the 2s-3s-4s chow meld was already claimed earlier.
		winningHand: ['1s', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', 'z5', 'z5'],
		patterns: [
			{ name: 'All Sequences', faan: 1 },
			{ name: 'No Flowers', faan: 1 },
			{ name: 'Self-Draw', faan: 1 },
			{ name: 'Half Flush', faan: 3 }
		],
		totalFaan: 6,
		payments: { 0: -16, 1: -16, 2: 48, 3: -16 }
	},
	handEndHoldMs: 8000,
	turnDurationMs: null
};

// Scenario 4: exhaustive draw -- same hold as a win, but no winner/patterns/payments; the
// overlay falls back to a plain draw summary whenever outcome !== 'win'.
export const handJustEndedDraw: MockGameState = {
	phase: 'HAND_OVER',
	turn: 3,
	dealer: 2,
	prevailing: 'E',
	handNo: 6,
	wallCount: 0,
	you: 0,
	claimWindow: null,
	seats: [
		emptySeat(0, { concealedCount: 13, discards: ['1s', '9p', 'z2', '4m'], score: 40 }),
		emptySeat(1, { concealedCount: 13, discards: ['2p', '3p', '7s'], score: -20 }),
		emptySeat(2, { concealedCount: 13, discards: ['9m', '1p', '5s'], score: 10 }),
		emptySeat(3, { concealedCount: 13, discards: ['8p', '2m'], score: -30 })
	],
	handResult: { outcome: 'exhaustive_draw' },
	handEndHoldMs: 8000,
	turnDurationMs: null
};

// scenario 5: a full EAST_ONLY game (一圈) just reached game_end -- no hold, since the wire only
// reaches game_end once the final hand's hold resolves. Four hands (dealer 0->1->2->3) is the minimum.
export const gameJustEnded: MockGameState = {
	phase: 'GAME_OVER',
	turn: 3,
	dealer: 3,
	prevailing: 'E',
	handNo: 4,
	wallCount: 0,
	you: 0,
	claimWindow: null,
	handResult: null,
	handEndHoldMs: null,
	turnDurationMs: null,
	seats: [
		emptySeat(0, { discards: ['1s', '9p', 'z2', '4m'], score: -30 }),
		emptySeat(1, { discards: ['2p', '3p', '7s'], score: 50 }),
		emptySeat(2, { discards: ['9m', '1p', '5s'], score: -30 }),
		emptySeat(3, { discards: ['8p', '2m'], score: 10 })
	],
	gameEnd: {
		rounds: [
			{
				handNo: 1,
				dealer: 0,
				prevailing: 'E',
				deltas: { 0: -24, 2: 24 },
				result: {
					outcome: 'win',
					winner: 2,
					winningHand: ['1s', '2s', '3s', '4s', '5s', '6s', '7s', '8s', '9s', 'z5', 'z5'],
					melds: [{ kind: 'chow', tiles: ['2s', '3s', '4s'] }],
					patterns: [{ name: 'Half Flush', faan: 3 }],
					totalFaan: 3,
					payments: { 0: -24, 2: 24 }
				}
			},
			{
				handNo: 2,
				dealer: 1,
				prevailing: 'E',
				deltas: { 0: -16, 1: 48, 2: -16, 3: -16 },
				result: {
					outcome: 'win',
					winner: 1,
					winningHand: [
						'z1',
						'z1',
						'z1',
						'z2',
						'z2',
						'z2',
						'z3',
						'z3',
						'z3',
						'z4',
						'z4',
						'z4',
						'z6'
					],
					patterns: [
						{ name: 'Self-Draw', faan: 1 },
						{ name: 'All Pungs', faan: 3 }
					],
					totalFaan: 4,
					payments: { 0: -16, 1: 48, 2: -16, 3: -16 }
				}
			},
			{
				handNo: 3,
				dealer: 2,
				prevailing: 'E',
				deltas: { 0: 10, 1: 10, 2: -30, 3: 10 },
				result: { outcome: 'exhaustive_draw' }
			},
			{
				handNo: 4,
				dealer: 3,
				prevailing: 'E',
				deltas: { 1: -8, 2: -8, 3: 16 },
				result: {
					outcome: 'win',
					winner: 3,
					winningHand: ['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', 'z7', 'z7'],
					patterns: [{ name: 'Chicken Hand', faan: 1 }],
					totalFaan: 1,
					payments: { 1: -8, 2: -8, 3: 16 }
				}
			}
		],
		standings: [
			{ seat: 1, total: 50 },
			{ seat: 3, total: 10 },
			{ seat: 0, total: -30 },
			{ seat: 2, total: -30 }
		]
	}
};

export interface MockScenario {
	id: string;
	label: string;
	state: MockGameState;
}

export const MOCK_SCENARIOS: MockScenario[] = [
	{ id: 'your-turn', label: 'Your turn to discard', state: yourTurnToDiscard },
	{ id: 'claim-window', label: 'Claim window open (you)', state: claimWindowOpenForYou },
	{ id: 'hand-ended', label: 'Hand just ended', state: handJustEnded },
	{ id: 'hand-ended-draw', label: 'Hand ended in a draw', state: handJustEndedDraw },
	{ id: 'game-ended', label: 'Game just ended', state: gameJustEnded }
];
