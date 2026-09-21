// Mock GameState-shaped fixture for the M4-groundwork /table assembly (this sub-task).
// Mirrors mahjong_core/state.py's GameState/SeatState/Phase (docs/03-frontend.md's
// cross-reference) closely enough to not be thrown away once real WS integration (M3+)
// replaces it with a reducer-fed store — field names track the Python dataclasses, just
// camelCased and pre-redacted for a single seat's point of view.
//
// Deliberately NOT modeled: the positional slot-array scheme for opponent concealed tiles
// (docs/03-frontend.md §4) — there's no event stream to diff against yet, so opponent hands
// here are a plain count. Real `TileCode`s only appear where the real protocol would reveal
// them to this seat: your own concealed hand/drawn tile, any open meld, and a finished hand's
// winning tiles.

import type { TileCode } from './tile-code';

export type Seat = 0 | 1 | 2 | 3;
export type Wind = 'E' | 'S' | 'W' | 'N';

// mirrors state.Phase (state.py); AWAIT_KONG_ROB/SCORING/GAME_OVER included for shape
// completeness even though no mock scenario below uses them yet.
export type Phase =
	| 'AWAIT_DRAW'
	| 'AWAIT_ACTION'
	| 'AWAIT_CLAIMS'
	| 'AWAIT_KONG_ROB'
	| 'SCORING'
	| 'HAND_OVER'
	| 'GAME_OVER';

// mirrors melds.MeldKind, minus PAIR (state.py's SeatState.melds never holds a bare pair).
export type MeldKind = 'chow' | 'pung' | 'exposed_kong' | 'concealed_kong' | 'added_kong';

export interface MockMeld {
	kind: MeldKind;
	// real tile identities always, even for a concealed_kong — melds.Meld never redacts;
	// TileFace is the thing responsible for rendering a concealed_kong as backs (§4's
	// "identity stays hidden... until hand end"), not this fixture.
	tiles: TileCode[];
	fromSeat?: Seat; // undefined for concealed_kong/added_kong, mirrors Meld.from_seat = None
}

// mirrors state.SeatState, redacted for a single point of view: `concealedHand` (real
// TileCodes) is only ever populated for the "you" seat; every other seat gets
// `concealedCount` only, per §4's "opponent hands are positional/count-only."
export interface MockSeatState {
	seat: Seat;
	name: string;
	concealedCount: number;
	concealedHand?: TileCode[]; // present only for the "you" seat
	drawn?: TileCode | null; // held-apart 14th tile; "you" seat only, real events redact this too
	melds: MockMeld[];
	discards: TileCode[];
	flowers: TileCode[];
	score: number;
	// wire `seat_status` (docs/00-architecture.md §5's `SeatView.seat_status`) -- optional since
	// no mock fixture sets it (mock scenarios have no bot concept); live-view.ts populates it
	// from `ClientGameState.seatStatus` for the one value the table scene renders today: `"bot"`
	// (M4.5 practice mode).
	status?: string;
}

export type Seats = [MockSeatState, MockSeatState, MockSeatState, MockSeatState];

export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

export interface MockClaimOption {
	kind: ClaimKind;
	tiles?: TileCode[];
}

// mirrors state.ClaimWindow, redacted: the real ClaimWindow.offers carries one ClaimOffer
// per eligible seat (never broadcasting who else can claim, per its docstring) — `yourOptions`
// is this seat's own offer only, `null` when this seat has none (server never sends an offer
// with nothing in it, so `null` is the "not offered" case, not an empty array).
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

// mirrors state.HandResult plus the faan_breakdown/payments shape FaanBreakdown.svelte
// already codifies (docs/02-protocol.md's hand_end sketch) -- only populated for outcome
// 'win'; an exhaustive_draw carries no winner/patterns/payments, same as HandResult itself.
export interface MockHandResult {
	outcome: HandOutcome;
	winner?: Seat;
	winType?: WinType;
	winningHand?: TileCode[];
	patterns?: FaanPatternMock[];
	totalFaan?: number;
	payments?: Partial<Record<Seat, number>>;
}

// mirrors ScoreSheet.svelte's own `RoundResult`, kept as a separate parallel type rather than
// importing it (same reasoning as `FaanPatternMock` above: this module has no UI-component
// dependency, mirrors server/mahjong_core shapes only) -- `live-view.ts`'s `meldToView` already
// does the equivalent tile_id -> `TileCode` conversion for the live path; a mock fixture has
// no ids to begin with, so it writes `TileCode`s directly, same as `MockHandResult` above.
export interface MockRoundResult {
	outcome: HandOutcome;
	winner?: Seat;
	winningHand?: TileCode[];
	melds?: MockMeld[];
	patterns?: FaanPatternMock[];
	totalFaan?: number;
	payments?: Partial<Record<Seat, number>>;
}

// mirrors ScoreSheet.svelte's `HandRecord`, minus the seat-name resolution ScoreSheet itself
// does from its own `seats` prop.
export interface MockScoreRound {
	handNo: number;
	dealer: Seat;
	prevailing: Wind;
	deltas: Partial<Record<Seat, number>>;
	result?: MockRoundResult;
}

// a completed game's full history + final ranking (ScoreSheet's own `standings`) -- present
// only on the one scenario that's actually reached `game_end` (below); every other scenario is
// mid-game and has no game-end summary to show.
export interface MockGameEndSummary {
	rounds: MockScoreRound[];
	standings: { seat: Seat; total: number }[];
}

// mirrors state.GameState, redacted to one seat's point of view. `you` names which seat that
// is -- always 0 in the scenarios below, but kept as a field (not hardcoded downstream) since
// the real per-seat redacted stream will vary it.
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
	// the hand-end hold's remaining time (docs/00-architecture.md §3 "Hand-end hold"): every
	// `HAND_OVER` hand end -- win or exhaustive draw alike -- holds the round open for this
	// long, or until every seat dismisses, whichever first. `null` whenever `handResult` is
	// (no hold to show); mirrors `claimWindow.durationMs`'s own shape one level up.
	handEndHoldMs: number | null;
	// this seat's own `AWAIT_ACTION` deadline (`ruleset.turn_seconds`, server/mahjong_core/
	// config.py): set whenever `turn === you`, whether this turn followed a normal draw or a
	// claimed meld (both arrive as the same `turn` event server-side, docs/00-architecture.md
	// §8) -- `null` whenever it's any other seat's turn. Mirrors `claimWindow.durationMs`'s own
	// "already-computed remaining ms" shape.
	turnDurationMs: number | null;
	you: Seat;
	/** Set only on the one scenario that's actually reached `game_end` -- `+page.svelte`'s
	 * `GameEndScreen` wiring reads this the same way it reads `liveStore.state.gameEnd` on the
	 * live path (docs/03-frontend.md's `/table/[id]` wiring section), so the auto-shown summary
	 * screen is reachable/screenshot-able with no backend running. */
	gameEnd?: MockGameEndSummary;
}

// (seat - you) mod 4, clockwise from you: 0 self, 1 right, 2 across, 3 left
// (docs/03-frontend.md's seat-colour comment in _tokens.scss: "self/right/across/left,
// clockwise from you").
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

// Scenario 1: your turn to discard. AWAIT_ACTION, turn = you (seat 0), you hold a drawn
// tile and must choose what to discard. No claim window, no hand result.
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

// Scenario 2: claim window open with options for you. AWAIT_CLAIMS, seat 1 just discarded
// a tile you (seat 0) can pung or win on. Turn still shows the last actor (seat 1) since the
// turn doesn't advance until the window resolves.
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

// Scenario 3: hand just ended with a win. HAND_OVER, seat 2 self-drew a Half Flush hand;
// FaanBreakdown overlay reads straight off handResult. Matches the plain-hand example already
// established in +page.svelte's FaanBreakdown demo, but as a self-draw so payments spread
// across all three other seats instead of one discarder.
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
		// concealed portion only -- the meld's 2s-3s-4s chow (seat 2's `melds` above) was already
		// claimed earlier in the hand, so it's not part of the concealed tiles at hand-end.
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
	// hand-end hold (docs/00-architecture.md §3): the demo's still-open countdown, not an
	// arbitrary prop -- a real `hand_end` always carries one, win or draw alike.
	handEndHoldMs: 8000,
	turnDurationMs: null
};

// Scenario 4: hand just ended in an exhaustive draw. Same HAND_OVER hold as a win
// (docs/00-architecture.md §3's "Hand-end hold" is uniform across outcomes), but with no
// winner/patterns/payments -- `+page.svelte`'s overlay falls back to a plain draw summary
// instead of `FaanBreakdown` whenever `outcome !== 'win'`.
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

// Scenario 5: a full EAST_ONLY game (一圈) just reached `game_end` -- GAME_OVER, no more hold
// (`handResult`/`handEndHoldMs` null, unlike scenarios 3/4 above: the real wire sequence only
// ever reaches `game_end` *after* the final hand's own hold has already resolved, docs/03
// -frontend.md's `/table/[id]` wiring section, so there's no lingering per-hand overlay to show
// alongside this one). Four hands is EAST_ONLY's minimum length (dealer 0->1->2->3, wrapping
// back to 0 ends the round): a discard win, a self-draw, an exhaustive draw, and a second
// discard win, deltas hand-checked to sum to zero per hand and accumulate to `standings`.
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
