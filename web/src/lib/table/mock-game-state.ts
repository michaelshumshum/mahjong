// frozen TableView fixtures (e2e + screenshots depend on them): pre-redacted for a single
// seat's view. Opponent hands are plain counts; TileCodes only where the wire would reveal them.

import type { Seat } from '$lib/game/types';
import type { TableView, SeatView } from './view-types';

const SEAT_NAMES = ['You', 'Bob', 'Carol', 'Dave'];

function emptySeat(seat: Seat, overrides: Partial<SeatView> = {}): SeatView {
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
export const yourTurnToDiscard: TableView = {
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
export const claimWindowOpenForYou: TableView = {
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
export const handJustEnded: TableView = {
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
		// canonical keys, as hand_end sends them; labels render through faanPatternLabel
		patterns: [
			{ name: '平糊', faan: 1 },
			{ name: '無花', faan: 1 },
			{ name: '自摸', faan: 1 },
			{ name: '混一色', faan: 3 }
		],
		totalFaan: 6,
		payments: { 0: -16, 1: -16, 2: 48, 3: -16 }
	},
	handEndHoldMs: 8000,
	turnDurationMs: null
};

// Scenario 4: exhaustive draw -- same hold as a win, but no winner/patterns/payments; the
// overlay falls back to a plain draw summary whenever outcome !== 'win'.
export const handJustEndedDraw: TableView = {
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
	handResult: {
		outcome: 'exhaustive_draw',
		// a real commit/reveal pair (SHA256(hand_seed || nonce)), so the badge reads as verified
		fairness: {
			handSeed: '3f9c2a7e41b06d58c3e1f2a49b7d0c6e8a5f13d24b9e70c6a1d8f3b25e4c7a09',
			nonce: '8d2e4f61a09b3c7e5d1f2a6b4c8e0d93',
			commit: 'bcdf31dea46c9d02561f12ccce044a365acae2a95d539b69726cb4bd8547f8dc'
		}
	},
	handEndHoldMs: 8000,
	turnDurationMs: null
};

// scenario 5: a full EAST_ONLY game (一圈) just reached game_end -- no hold, since the wire only
// reaches game_end once the final hand's hold resolves. Four hands (dealer 0->1->2->3) is the minimum.
export const gameJustEnded: TableView = {
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
					patterns: [{ name: '混一色', faan: 3 }],
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
						{ name: '自摸', faan: 1 },
						{ name: '對對糊', faan: 3 }
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
					patterns: [{ name: '雞糊', faan: 1 }],
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

// Scenario 6: late in a hand -- full discard pools, every opponent heavily melded. Stresses the
// phone layouts (pool wrapping, meld rows), which the early-hand fixtures never fill.
export const lateHandCrowded: TableView = {
	...yourTurnToDiscard,
	handNo: 6,
	wallCount: 9,
	lastDiscard: { seat: 3, index: 19 },
	seats: [
		emptySeat(0, {
			concealedCount: 7,
			concealedHand: ['2m', '3m', '4m', '6p', '6p', '7s', '8s'],
			drawn: '9s',
			melds: [
				{ kind: 'pung', tiles: ['z5', 'z5', 'z5'], fromSeat: 2 },
				{ kind: 'chow', tiles: ['3p', '4p', '5p'], fromSeat: 3 }
			],
			flowers: ['f1', 'f5'],
			discards: [
				'1s',
				'9p',
				'z2',
				'1m',
				'z3',
				'9m',
				'5s',
				'2p',
				'8m',
				'z4',
				'1p',
				'7m',
				'3s',
				'z6',
				'6m',
				'4s',
				'9p',
				'2s',
				'5m'
			],
			score: 40
		}),
		emptySeat(1, {
			concealedCount: 1,
			melds: [
				{ kind: 'pung', tiles: ['z1', 'z1', 'z1'], fromSeat: 3 },
				{ kind: 'chow', tiles: ['6m', '7m', '8m'], fromSeat: 0 },
				{ kind: 'exposed_kong', tiles: ['4p', '4p', '4p', '4p'], fromSeat: 2 },
				{ kind: 'concealed_kong', tiles: ['8s', '8s', '8s', '8s'] }
			],
			flowers: ['f3', 'f6', 'f8'],
			discards: [
				'2p',
				'3p',
				'7s',
				'z4',
				'1m',
				'9s',
				'z2',
				'5p',
				'3m',
				'6s',
				'1p',
				'z7',
				'8p',
				'2s',
				'9m',
				'4m',
				'z3',
				'7p',
				'1s',
				'6p'
			],
			score: -20
		}),
		emptySeat(2, {
			concealedCount: 4,
			melds: [
				{ kind: 'chow', tiles: ['1s', '2s', '3s'], fromSeat: 1 },
				{ kind: 'pung', tiles: ['z6', 'z6', 'z6'], fromSeat: 0 },
				{ kind: 'pung', tiles: ['9p', '9p', '9p'], fromSeat: 3 }
			],
			flowers: ['f2'],
			discards: [
				'9m',
				'1p',
				'5s',
				'6s',
				'z6',
				'2m',
				'8s',
				'z1',
				'4s',
				'7m',
				'3p',
				'z4',
				'5m',
				'2p',
				'9s',
				'1m',
				'6p',
				'z2',
				'8m',
				'3s',
				'7p'
			],
			score: 10
		}),
		emptySeat(3, {
			concealedCount: 7,
			melds: [
				{ kind: 'chow', tiles: ['4m', '5m', '6m'], fromSeat: 2 },
				{ kind: 'exposed_kong', tiles: ['z7', 'z7', 'z7', 'z7'], fromSeat: 1 }
			],
			discards: [
				'8p',
				'2m',
				'z3',
				'7s',
				'1s',
				'5p',
				'9m',
				'z4',
				'3m',
				'6s',
				'2p',
				'8m',
				'z1',
				'4p',
				'7m',
				'1p',
				'9s',
				'3p',
				'z2',
				'6m'
			],
			score: -30
		})
	]
};

export interface MockScenario {
	id: string;
	label: string;
	state: TableView;
}

export const MOCK_SCENARIOS: MockScenario[] = [
	{ id: 'your-turn', label: 'Your turn to discard', state: yourTurnToDiscard },
	{ id: 'claim-window', label: 'Claim window open (you)', state: claimWindowOpenForYou },
	{ id: 'hand-ended', label: 'Hand just ended', state: handJustEnded },
	{ id: 'hand-ended-draw', label: 'Hand ended in a draw', state: handJustEndedDraw },
	{ id: 'game-ended', label: 'Game just ended', state: gameJustEnded },
	{ id: 'late-hand', label: 'Late hand, crowded table', state: lateHandCrowded }
];
