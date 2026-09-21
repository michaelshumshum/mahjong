import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { reduce } from '../net/reducer';
import { initialClientGameState } from '../game/state';
import { viewFromClientState } from './live-view';
import type { ServerEvent } from '../net/protocol';

describe('viewFromClientState own-hand split', () => {
	it('shows no held-apart tile after claiming a pung -- only after a real draw', () => {
		let state = initialClientGameState();
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'state_sync',
			d: {
				seat: 1,
				hand_no: 1,
				prevailing: 'E',
				dealer: 0,
				turn: 0,
				phase: 'AWAIT_ACTION',
				own_hand: [4, 5, 8, 12, 16],
				concealed_counts: [13, 5, 13, 13],
				melds: [[], [], [], []],
				discard_pools: [[0], [], [], []],
				flowers: [[], [], [], []],
				wall_remaining: 50,
				seat_status: ['bot', 'human', 'bot', 'bot'],
				names: [null, null, null, null],
				host_seat: null,
				scores: [0, 0, 0, 0],
				legal_actions: [],
				deadline_ts: null,
				claim_options: []
			}
		} as ServerEvent);

		// seat 1 pungs seat 0's discard (tile_id 6, same type as the 4/5 already held) using two
		// of its own concealed tiles -- the claimed tile never touches `ownHand`.
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 2,
			t: 'meld',
			d: { seat: 1, meld_kind: 'pung', tiles: [4, 5, 6], from_seat: 0 }
		} as ServerEvent);
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 3,
			t: 'turn',
			d: { seat: 1, phase: 'AWAIT_ACTION', deadline_ts: 5000, legal: [{ kind: 'discard' }] }
		} as ServerEvent);

		const live = viewFromClientState(state);
		expect(live).not.toBeNull();
		// regression: the old "last tile in ownHand" heuristic would have pulled tile 16 -- an
		// already-owned tile, never drawn -- out to the side as if it had just been added.
		expect(live!.ownHand.drawnId).toBeNull();
		expect(live!.ownHand.concealedIds.slice().sort((a, b) => a - b)).toEqual([8, 12, 16]);
	});

	it('still shows the held-apart tile after a real draw', () => {
		let state = initialClientGameState();
		state = { ...state, seat: 0, ownHand: [4, 8], concealedCounts: [2, 13, 13, 13] };
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'draw',
			d: { seat: 0, tile_id: 99 }
		} as ServerEvent);
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 2,
			t: 'turn',
			d: { seat: 0, phase: 'AWAIT_ACTION', deadline_ts: 5000, legal: [{ kind: 'discard' }] }
		} as ServerEvent);

		const live = viewFromClientState(state);
		expect(live!.ownHand.drawnId).toBe(99);
		expect(live!.ownHand.concealedIds).toEqual([4, 8]);
	});
});

describe('viewFromClientState turnDurationMs', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.setSystemTime(0);
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it("reflects this seat's own deadline, whether the turn followed a draw or a claimed meld", () => {
		let state = initialClientGameState();
		state = { ...state, seat: 1 };
		// same "seat 1 pungs, then gets a turn" shape as the own-hand-split test above --
		// the discard-after-claim turn carries a deadline exactly like a normal draw turn does.
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'turn',
			d: { seat: 1, phase: 'AWAIT_ACTION', deadline_ts: 5000, legal: [{ kind: 'discard' }] }
		} as ServerEvent);

		const live = viewFromClientState(state);
		expect(live!.view.turnDurationMs).toBe(5000);
	});

	it('is null once this seat has discarded, clearing deadlineTs', () => {
		let state = initialClientGameState();
		state = { ...state, seat: 0 };
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'turn',
			d: { seat: 0, phase: 'AWAIT_ACTION', deadline_ts: 5000, legal: [{ kind: 'discard' }] }
		} as ServerEvent);
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 2,
			t: 'discard',
			d: { seat: 0, tile_id: 4, tile: '1m', pool_index: 0 }
		} as ServerEvent);

		const live = viewFromClientState(state);
		expect(live!.view.turnDurationMs).toBeNull();
	});

	it("is null for another seat's turn", () => {
		let state = initialClientGameState();
		state = { ...state, seat: 0 };
		state = reduce(state, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'turn',
			d: { seat: 2, phase: 'AWAIT_ACTION', deadline_ts: 5000, legal: [] }
		} as ServerEvent);

		const live = viewFromClientState(state);
		expect(live!.view.turnDurationMs).toBeNull();
	});
});
