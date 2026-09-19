import { describe, expect, it } from 'vitest';
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
