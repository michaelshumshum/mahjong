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
	you: Seat;
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
			melds: [],
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
		winningHand: [
			'1s',
			'2s',
			'3s',
			'4s',
			'5s',
			'6s',
			'7s',
			'8s',
			'9s',
			'2s',
			'3s',
			'4s',
			'z5',
			'z5'
		],
		patterns: [
			{ name: 'All Sequences', faan: 1 },
			{ name: 'No Flowers', faan: 1 },
			{ name: 'Self-Draw', faan: 1 },
			{ name: 'Half Flush', faan: 3 }
		],
		totalFaan: 6,
		payments: { 0: -16, 1: -16, 2: 48, 3: -16 }
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
	{ id: 'hand-ended', label: 'Hand just ended', state: handJustEnded }
];
