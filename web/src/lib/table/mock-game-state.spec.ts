import { describe, expect, it } from 'vitest';
import type { Seat } from '$lib/game/types';
import { MOCK_SCENARIOS } from './mock-game-state';
import type { MockGameState, MockSeatState } from './view-types';

const VALID_PHASES = new Set([
	'AWAIT_DRAW',
	'AWAIT_ACTION',
	'AWAIT_CLAIMS',
	'AWAIT_KONG_ROB',
	'SCORING',
	'HAND_OVER',
	'GAME_OVER'
]);

function assertValidSeat(seat: MockSeatState, you: Seat, phase: string): void {
	expect(seat.seat).toBeGreaterThanOrEqual(0);
	expect(seat.seat).toBeLessThan(4);
	expect(seat.name).toBeTruthy();
	expect(seat.concealedCount).toBeGreaterThanOrEqual(0);
	expect(seat.melds).toBeDefined();
	expect(seat.discards).toBeDefined();
	expect(seat.flowers).toBeDefined();
	expect(typeof seat.score).toBe('number');

	// only the "you" seat reveals its concealed hand during active play; end-of-hand states
	// are redacted the same as opponents.
	const activePhases = new Set(['AWAIT_DRAW', 'AWAIT_ACTION', 'AWAIT_CLAIMS', 'AWAIT_KONG_ROB']);
	if (seat.seat === you && activePhases.has(phase)) {
		expect(seat.concealedHand).toBeDefined();
		expect(seat.concealedHand).toHaveLength(seat.concealedCount);
	} else {
		expect(seat.concealedHand).toBeUndefined();
	}

	// drawn tile is only meaningful for the "you" seat and only in AWAIT_ACTION.
	if (seat.seat !== you || phase !== 'AWAIT_ACTION') {
		expect(seat.drawn === null || seat.drawn === undefined).toBe(true);
	}
}

function assertValidState(state: MockGameState): void {
	expect(VALID_PHASES.has(state.phase)).toBe(true);
	expect(state.turn).toBeGreaterThanOrEqual(0);
	expect(state.turn).toBeLessThan(4);
	expect(state.dealer).toBeGreaterThanOrEqual(0);
	expect(state.dealer).toBeLessThan(4);
	expect(['E', 'S', 'W', 'N'] as const).toContain(state.prevailing);
	expect(state.handNo).toBeGreaterThan(0);
	expect(state.wallCount).toBeGreaterThanOrEqual(0);
	expect(state.you).toBe(0);
	expect(state.seats).toHaveLength(4);
	expect(state.seats.map((s) => s.seat)).toEqual([0, 1, 2, 3]);

	for (const seat of state.seats) {
		assertValidSeat(seat, state.you, state.phase);
	}

	if (state.claimWindow) {
		expect(state.claimWindow.sourceSeat).toBeGreaterThanOrEqual(0);
		expect(state.claimWindow.sourceSeat).toBeLessThan(4);
		expect(state.claimWindow.yourOptions === null || state.claimWindow.yourOptions.length > 0).toBe(
			true
		);
	}

	if (state.handResult) {
		expect(['win', 'exhaustive_draw'] as const).toContain(state.handResult.outcome);
		if (state.handResult.outcome === 'win') {
			expect(state.handResult.winner).toBeGreaterThanOrEqual(0);
			expect(state.handResult.winner).toBeLessThan(4);
			expect(state.handResult.winType).toBeTruthy();
			expect(state.handResult.totalFaan).toBeGreaterThan(0);
			expect(state.handResult.payments).toBeDefined();
		}
	}

	if (state.phase === 'HAND_OVER') {
		expect(state.handResult).not.toBeNull();
		expect(state.handEndHoldMs).toBeGreaterThan(0);
	} else if (state.phase === 'GAME_OVER') {
		expect(state.gameEnd).toBeDefined();
		expect(state.gameEnd!.rounds.length).toBeGreaterThan(0);
		expect(state.gameEnd!.standings).toHaveLength(4);
	}
}

describe('MOCK_SCENARIOS', () => {
	it('has unique ids and non-empty labels', () => {
		const ids = MOCK_SCENARIOS.map((s) => s.id);
		expect(new Set(ids).size).toBe(ids.length);
		for (const scenario of MOCK_SCENARIOS) {
			expect(scenario.id).toBeTruthy();
			expect(scenario.label).toBeTruthy();
		}
	});

	it('contains the expected scenarios', () => {
		expect(MOCK_SCENARIOS.map((s) => s.id)).toEqual([
			'your-turn',
			'claim-window',
			'hand-ended',
			'hand-ended-draw',
			'game-ended',
			'late-hand'
		]);
	});

	it('produces valid state shapes', () => {
		for (const scenario of MOCK_SCENARIOS) {
			assertValidState(scenario.state);
		}
	});

	it('lets scenarios be selected by id', () => {
		const selected = MOCK_SCENARIOS.find((s) => s.id === 'claim-window');
		expect(selected).toBeDefined();
		expect(selected!.state.phase).toBe('AWAIT_CLAIMS');
		expect(selected!.state.claimWindow).not.toBeNull();
	});

	it('keeps the game-ended scenario in GAME_OVER with a summary', () => {
		const ended = MOCK_SCENARIOS.find((s) => s.id === 'game-ended');
		expect(ended).toBeDefined();
		expect(ended!.state.phase).toBe('GAME_OVER');
		expect(ended!.state.gameEnd).toBeDefined();
	});
});
