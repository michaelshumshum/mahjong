import { describe, it, expect, vi } from 'vitest';
import { reduce } from './reducer';
import { initialClientGameState, type ClientGameState } from '../game/state';
import type { ServerEvent } from './protocol';

function state(patch: Partial<ClientGameState> = {}): ClientGameState {
	return { ...initialClientGameState(), ...patch };
}

describe('reduce', () => {
	it('is a no-op for pong', () => {
		const s = state();
		const event: ServerEvent = { v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: 10, t1: 20 } };

		expect(reduce(s, event)).toBe(s);
	});

	it('logs and no-ops for error events', () => {
		const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
		const s = state();
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'error',
			d: { code: 'bad_frame', message: 'boom' }
		};

		expect(reduce(s, event)).toBe(s);
		expect(spy).toHaveBeenCalledWith('[reducer] server error', 'bad_frame', 'boom');
		spy.mockRestore();
	});

	it('is a no-op for ack (sender-only bookkeeping)', () => {
		const s = state();
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'ack',
			d: { id: 'c-1', ok: true }
		};

		expect(reduce(s, event)).toBe(s);
	});

	it('state_sync fully replaces state, including own seat and an embedded claim offer', () => {
		const s = state({ seat: null, ownHand: [1, 2, 3] });
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 5,
			t: 'state_sync',
			d: {
				seat: 2,
				hand_no: 3,
				prevailing: 'E',
				dealer: 1,
				turn: 2,
				phase: 'AWAIT_CLAIMS',
				own_hand: [10, 11, 12],
				concealed_counts: [13, 13, 12, 13],
				melds: [[], [], [{ kind: 'pung', tiles: [4, 4, 4], from_seat: 0 }], []],
				discard_pools: [[], [], [7], []],
				flowers: [[], [], [], []],
				wall_remaining: 80,
				seat_status: ['connected', 'connected', 'connected', 'connected'],
				names: ['Alice', 'Bob', null, 'Dave'],
				scores: [0, 0, 0, 0],
				legal_actions: [],
				claim_options: [{ kind: 'pung', tiles: [4, 4] }],
				deadline_ts: 1000
			}
		};

		const next = reduce(s, event);

		expect(next.seat).toBe(2);
		expect(next.ownHand).toEqual([10, 11, 12]);
		expect(next.melds[2]).toEqual([{ kind: 'pung', tiles: [4, 4, 4], count: null, fromSeat: 0 }]);
		expect(next.names).toEqual(['Alice', 'Bob', null, 'Dave']);
		expect(next.claimOffer).toEqual({
			windowId: null,
			options: [{ kind: 'pung', tiles: [4, 4] }],
			deadlineTs: 1000
		});
		// `d.turn` (2) is the discarder for the embedded window's whole lifetime, and its pool's
		// last entry (7) is the tile the offered `claim_options` are about (live-view.ts's
		// `claimWindowToView` reads this to show what's actually being claimed).
		expect(next.lastDiscard).toEqual({ seat: 2, tileId: 7 });
	});

	it('state_sync with no embedded claim window leaves lastDiscard null', () => {
		const s = state({ lastDiscard: { seat: 0, tileId: 47 } });
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 5,
			t: 'state_sync',
			d: {
				seat: 0,
				hand_no: 3,
				prevailing: 'E',
				dealer: 1,
				turn: 0,
				phase: 'AWAIT_ACTION',
				own_hand: [10, 11, 12],
				concealed_counts: [13, 13, 12, 13],
				melds: [[], [], [], []],
				discard_pools: [[7], [], [], []],
				flowers: [[], [], [], []],
				wall_remaining: 80,
				seat_status: ['connected', 'connected', 'connected', 'connected'],
				names: ['Alice', 'Bob', null, 'Dave'],
				scores: [0, 0, 0, 0],
				legal_actions: [{ kind: 'discard' }],
				claim_options: [],
				deadline_ts: 1000
			}
		};

		expect(reduce(s, event).lastDiscard).toBeNull();
	});

	it('hand_start resets per-hand fields but not scores', () => {
		const s = state({
			ownHand: [1, 2, 3],
			discardPools: [[9], [], [], []],
			scores: [10, 20, 30, 40],
			lastDiscard: { seat: 0, tileId: 9 },
			lastHandEnd: {
				handNo: 1,
				outcome: 'win',
				winner: 0,
				winType: 'self_draw',
				discarder: null,
				faan: 3,
				faanBreakdown: null,
				points: 100,
				payments: null,
				revealed: true,
				winningHand: [1, 2, 3]
			},
			handEndDeadlineTs: 5000
		});
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'hand_start',
			d: {
				hand_no: 2,
				prevailing: 'E',
				dealer: 1,
				seats: ['connected', 'connected', 'connected', 'connected']
			}
		};

		const next = reduce(s, event);

		expect(next.handNo).toBe(2);
		expect(next.ownHand).toEqual([]);
		expect(next.discardPools).toEqual([[], [], [], []]);
		expect(next.lastHandEnd).toBeNull();
		expect(next.handEndDeadlineTs).toBeNull();
		expect(next.lastDiscard).toBeNull();
		expect(next.scores).toEqual([10, 20, 30, 40]);
	});

	it('draw appends to own hand, bumps others counts only, and decrements wallRemaining', () => {
		const s = state({
			seat: 0,
			ownHand: [1, 2],
			concealedCounts: [2, 13, 13, 13],
			wallRemaining: 50
		});

		const ownDraw = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'draw',
			d: { seat: 0, tile_id: 99 }
		});
		expect(ownDraw.ownHand).toEqual([1, 2, 99]);
		expect(ownDraw.concealedCounts[0]).toBe(3);
		expect(ownDraw.wallRemaining).toBe(49);

		const oppDraw = reduce(s, { v: 1, ts: 1, seq: 1, t: 'draw', d: { seat: 1 } });
		expect(oppDraw.ownHand).toEqual([1, 2]);
		expect(oppDraw.concealedCounts[1]).toBe(14);
		expect(oppDraw.wallRemaining).toBe(49);
	});

	it('flower_replace decrements wallRemaining for the drawn flower', () => {
		const s = state({ seat: 0, wallRemaining: 50, flowers: [[], [], [], []] });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'flower_replace',
			d: { seat: 0, flower: 'f1' }
		});
		expect(next.flowers[0]).toEqual(['f1']);
		expect(next.wallRemaining).toBe(49);
	});

	it('discard removes from own hand, decrements the discarder count, and records the pool', () => {
		const s = state({ seat: 0, ownHand: [1, 2, 47], concealedCounts: [3, 13, 13, 13] });
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'discard',
			d: { seat: 0, tile_id: 47, tile: '5s', pool_index: 0 }
		};

		const next = reduce(s, event);

		expect(next.ownHand).toEqual([1, 2]);
		expect(next.concealedCounts[0]).toBe(2);
		expect(next.discardPools[0]).toEqual([47]);
		expect(next.lastDiscard).toEqual({ seat: 0, tileId: 47 });
	});

	it('a later discard overwrites lastDiscard rather than accumulating', () => {
		const s = state({ lastDiscard: { seat: 0, tileId: 47 } });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'discard',
			d: { seat: 2, tile_id: 90, tile: 'z5', pool_index: 0 }
		});

		expect(next.lastDiscard).toEqual({ seat: 2, tileId: 90 });
	});

	it("discarding clears this seat's own stale legalActions/deadlineTs, but not another seat's discard", () => {
		// reproduces a real live-game bug (docs/03-frontend.md §6 sub-task): every entry left in
		// `legalActions` after a discard still names a tile_id genuinely still in `ownHand` (only
		// the discarded one is gone), so a UI reading `legalActions` alone can't tell the whole
		// set is stale -- it kept looking actionable, letting a second click send a discard the
		// server silently drops as out-of-turn (docs/02-protocol.md §1's ack note).
		const own = state({
			seat: 0,
			ownHand: [1, 2, 47],
			concealedCounts: [3, 13, 13, 13],
			legalActions: [
				{ kind: 'discard', tile_id: 1 },
				{ kind: 'discard', tile_id: 2 }
			],
			deadlineTs: 5000
		});
		const ownDiscard = reduce(own, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'discard',
			d: { seat: 0, tile_id: 47, tile: '5s', pool_index: 0 }
		});
		expect(ownDiscard.legalActions).toEqual([]);
		expect(ownDiscard.deadlineTs).toBeNull();

		const other = state({
			seat: 1,
			legalActions: [{ kind: 'pass' }],
			deadlineTs: 9000
		});
		const otherDiscard = reduce(other, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'discard',
			d: { seat: 0, tile_id: 47, tile: '5s', pool_index: 0 }
		});
		expect(otherDiscard.legalActions).toEqual([{ kind: 'pass' }]);
		expect(otherDiscard.deadlineTs).toBe(9000);
	});

	describe('claim window', () => {
		it('claim_offer opens the window, claim_resolved for that window_id closes it', () => {
			const s = state();
			const offered = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'claim_offer',
				d: { window_id: 204, options: [{ kind: 'pung', tiles: [31, 88] }], deadline_ts: 5000 }
			});
			expect(offered.claimOffer).toEqual({
				windowId: 204,
				options: [{ kind: 'pung', tiles: [31, 88] }],
				deadlineTs: 5000
			});

			const resolved = reduce(offered, {
				v: 1,
				ts: 1,
				seq: 2,
				t: 'claim_resolved',
				d: { window_id: 204, claim_kind: 'discard', seat: 1, action_kind: 'claim_pung' }
			});
			expect(resolved.claimOffer).toBeNull();
		});

		it('a stale claim_resolved for a superseded window_id is ignored', () => {
			const s = state({
				claimOffer: { windowId: 205, options: [{ kind: 'pass' }], deadlineTs: 6000 }
			});
			const next = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'claim_resolved',
				d: { window_id: 204, claim_kind: 'discard', seat: null, action_kind: null }
			});
			expect(next.claimOffer).toEqual(s.claimOffer);
		});

		it('turn clears any lingering claim offer for this seat', () => {
			const s = state({
				claimOffer: { windowId: 1, options: [{ kind: 'pass' }], deadlineTs: 100 }
			});
			const next = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'turn',
				d: { seat: 0, phase: 'AWAIT_ACTION', deadline_ts: 200, legal: [{ kind: 'discard' }] }
			});
			expect(next.claimOffer).toBeNull();
			expect(next.legalActions).toEqual([{ kind: 'discard' }]);
		});
	});

	describe('kong variants', () => {
		it('concealed_kong removes 4 tiles from the owner hand and count; kong_replace restores one', () => {
			const s = state({
				seat: 0,
				ownHand: [1, 1, 1, 1, 2, 3],
				concealedCounts: [6, 13, 13, 13],
				wallRemaining: 50
			});
			const melded = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'meld',
				d: { seat: 0, meld_kind: 'concealed_kong', tiles: [1, 1, 1, 1], from_seat: null }
			});
			expect(melded.ownHand).toEqual([2, 3]);
			expect(melded.concealedCounts[0]).toBe(2);
			expect(melded.melds[0]).toEqual([
				{ kind: 'concealed_kong', tiles: [1, 1, 1, 1], count: null, fromSeat: null }
			]);

			const replaced = reduce(melded, {
				v: 1,
				ts: 1,
				seq: 2,
				t: 'kong_replace',
				d: { seat: 0, tile_id: 55 }
			});
			expect(replaced.ownHand).toEqual([2, 3, 55]);
			expect(replaced.concealedCounts[0]).toBe(3);
			expect(replaced.wallRemaining).toBe(49);
		});

		it('a non-owner concealed_kong only carries a count, never redacts to real tiles', () => {
			const s = state({ seat: 0, concealedCounts: [13, 6, 13, 13] });
			const next = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'meld',
				d: { seat: 1, meld_kind: 'concealed_kong', tiles: null, count: 4 }
			});
			expect(next.melds[1]).toEqual([
				{ kind: 'concealed_kong', tiles: null, count: 4, fromSeat: null }
			]);
			expect(next.concealedCounts[1]).toBe(2);
		});

		it('added_kong replaces the existing pung meld in place rather than duplicating it', () => {
			const s = state({
				seat: 0,
				ownHand: [9, 1, 2],
				concealedCounts: [3, 13, 13, 13],
				melds: [[{ kind: 'pung', tiles: [4, 4, 4], count: null, fromSeat: 2 }], [], [], []]
			});
			const next = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'meld',
				d: { seat: 0, meld_kind: 'added_kong', tiles: [4, 4, 4, 9], from_seat: null }
			});

			expect(next.melds[0]).toEqual([
				{ kind: 'added_kong', tiles: [4, 4, 4, 9], count: null, fromSeat: null }
			]);
			expect(next.ownHand).toEqual([1, 2]);
			expect(next.concealedCounts[0]).toBe(2);
		});

		it('a claimed pung removes only the tiles the claiming seat actually held', () => {
			const s = state({ seat: 1, ownHand: [88, 31, 5], concealedCounts: [13, 3, 13, 13] });
			const next = reduce(s, {
				v: 1,
				ts: 1,
				seq: 1,
				t: 'meld',
				d: { seat: 1, meld_kind: 'pung', tiles: [31, 88, 47], from_seat: 0 }
			});
			expect(next.ownHand).toEqual([5]);
			expect(next.concealedCounts[1]).toBe(1);
		});
	});

	it('hand_end records the payload and clears turn/claim state', () => {
		const s = state({
			claimOffer: { windowId: 1, options: [], deadlineTs: 1 },
			legalActions: [{ kind: 'discard' }],
			deadlineTs: 42
		});
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'hand_end',
			d: {
				hand_no: 1,
				outcome: 'win',
				winner: 0,
				win_type: 'self_draw',
				discarder: null,
				faan: 3,
				faan_breakdown: { chicken_hand: 1 },
				points: 100,
				payments: { 0: 300, 1: -100, 2: -100, 3: -100 },
				revealed: true,
				winning_hand: [1, 2, 3],
				deadline_ts: 9000
			}
		});

		expect(next.lastHandEnd?.winner).toBe(0);
		expect(next.handEndDeadlineTs).toBe(9000);
		expect(next.claimOffer).toBeNull();
		expect(next.legalActions).toEqual([]);
		expect(next.deadlineTs).toBeNull();
	});

	it("hand_end also appends to handHistory, capturing this hand's dealer/prevailing", () => {
		const s = state({ dealer: 2, prevailing: 'SOUTH' });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'hand_end',
			d: {
				hand_no: 1,
				outcome: 'win',
				winner: 0,
				win_type: 'self_draw',
				discarder: null,
				faan: 3,
				faan_breakdown: { chicken_hand: 1 },
				points: 100,
				payments: { 0: 300, 1: -100, 2: -100, 3: -100 },
				revealed: true,
				winning_hand: [1, 2, 3],
				deadline_ts: 9000
			}
		});

		expect(next.handHistory).toEqual([{ ...next.lastHandEnd, dealer: 2, prevailing: 'SOUTH' }]);
	});

	it('multiple hand_end events across a sequence grow handHistory rather than overwrite it', () => {
		const handEnd = (handNo: number): ServerEvent => ({
			v: 1,
			ts: 1,
			seq: handNo,
			t: 'hand_end',
			d: {
				hand_no: handNo,
				outcome: 'win',
				winner: 0,
				win_type: 'self_draw',
				discarder: null,
				faan: 1,
				faan_breakdown: null,
				points: 10,
				payments: { 0: 30, 1: -10, 2: -10, 3: -10 },
				revealed: true,
				winning_hand: null,
				deadline_ts: 9000
			}
		});

		// dealer patched directly between hands, standing in for the hand_start that would
		// normally rotate it in a real stream (this reducer.ts case is covered separately above).
		let s = state({ dealer: 0 });
		s = reduce(s, handEnd(1));
		s = reduce({ ...s, dealer: 1 }, handEnd(2));
		s = reduce({ ...s, dealer: 2 }, handEnd(3));

		expect(s.handHistory.map((h) => h.handNo)).toEqual([1, 2, 3]);
		expect(s.handHistory.map((h) => h.dealer)).toEqual([0, 1, 2]);
		// only the latest hand's result is the "just finished" overlay value
		expect(s.lastHandEnd?.handNo).toBe(3);
	});

	it('hand_end does not duplicate an already-recorded hand_no in handHistory', () => {
		const s = state();
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'hand_end',
			d: {
				hand_no: 1,
				outcome: 'exhaustive_draw',
				winner: null,
				win_type: null,
				discarder: null,
				faan: null,
				faan_breakdown: null,
				points: null,
				payments: null,
				revealed: true,
				winning_hand: null,
				deadline_ts: 9000
			}
		};

		const once = reduce(s, event);
		const twice = reduce(once, event);

		expect(twice.handHistory).toHaveLength(1);
	});

	it('state_sync preserves accumulated handHistory (a redacted snapshot carries no hand history)', () => {
		const s = state({
			handHistory: [
				{
					handNo: 1,
					outcome: 'win',
					winner: 0,
					winType: 'self_draw',
					discarder: null,
					faan: 3,
					faanBreakdown: null,
					points: 100,
					payments: { 0: 300, 1: -100, 2: -100, 3: -100 },
					revealed: true,
					winningHand: null,
					dealer: 0,
					prevailing: 'EAST'
				}
			]
		});
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 5,
			t: 'state_sync',
			d: {
				seat: 2,
				hand_no: 2,
				prevailing: 'E',
				dealer: 1,
				turn: 2,
				phase: 'AWAIT_ACTION',
				own_hand: [10, 11, 12],
				concealed_counts: [13, 13, 12, 13],
				melds: [[], [], [], []],
				discard_pools: [[], [], [], []],
				flowers: [[], [], [], []],
				wall_remaining: 80,
				seat_status: ['connected', 'connected', 'connected', 'connected'],
				names: ['Alice', 'Bob', 'Carol', 'Dave'],
				scores: [300, -100, -100, -100],
				legal_actions: [],
				claim_options: [],
				deadline_ts: null
			}
		};

		const next = reduce(s, event);

		expect(next.handHistory).toEqual(s.handHistory);
	});

	it('game_end records final scores', () => {
		const s = state();
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'game_end',
			d: { hand_no: 8, scores: [500, -200, -100, -200] }
		});
		expect(next.gameEnd).toEqual({ handNo: 8, scores: [500, -200, -100, -200] });
		expect(next.scores).toEqual([500, -200, -100, -200]);
	});

	it('seat_state updates a single seat status, leaving the others untouched', () => {
		const s = state({ seatStatus: ['connected', 'connected', 'connected', 'connected'] });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'seat_state',
			d: { seat: 2, status: 'disconnected' }
		});
		expect(next.seatStatus).toEqual(['connected', 'connected', 'disconnected', 'connected']);
	});

	it('seat_state updates a single seat name, leaving the others untouched', () => {
		const s = state({ names: ['Alice', null, null, null] });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'seat_state',
			d: { seat: 1, status: 'connected', name: 'Bob' }
		});
		expect(next.names).toEqual(['Alice', 'Bob', null, null]);
	});

	it('seat_state with no name field leaves names untouched', () => {
		const s = state({ names: ['Alice', 'Bob', null, null] });
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'seat_state',
			d: { seat: 2, status: 'connected' }
		});
		expect(next.names).toEqual(['Alice', 'Bob', null, null]);
	});

	it('server_shutdown records the drain deadline', () => {
		const s = state();
		const next = reduce(s, {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'server_shutdown',
			d: { deadline_ts: 123456 }
		});
		expect(next.shutdownDeadlineTs).toBe(123456);
	});
});
