import { describe, it, expect } from 'vitest';
import { GameStore } from './store.svelte';
import type { MahjongSocket } from '../net/socket';
import type { Seat, ServerEvent } from '../net/protocol';
import type { ConnectionStatus } from './state';

/** Fake MahjongSocket for testing store wiring. Needs the 'client' vitest project —
 * `$effect`/`$effect.root` no-op under the 'server' project's SSR compile target. */
class FakeSocket {
	#eventListeners = new Set<(e: ServerEvent) => void>();
	#statusListeners = new Set<(s: ConnectionStatus) => void>();
	setSeatCalls: (number | null)[] = [];

	onEvent(listener: (e: ServerEvent) => void): () => void {
		this.#eventListeners.add(listener);
		return () => this.#eventListeners.delete(listener);
	}

	onStatus(listener: (s: ConnectionStatus) => void): () => void {
		this.#statusListeners.add(listener);
		return () => this.#statusListeners.delete(listener);
	}

	setSeat(seat: number | null): void {
		this.setSeatCalls.push(seat);
	}

	emit(event: ServerEvent): void {
		for (const l of this.#eventListeners) l(event);
	}

	emitStatus(status: ConnectionStatus): void {
		for (const l of this.#statusListeners) l(status);
	}

	get listenerCount(): number {
		return this.#eventListeners.size;
	}
}

function stateSyncEvent(seat: Seat | null, seq: number): ServerEvent {
	return {
		v: 1,
		ts: 1,
		seq,
		t: 'state_sync',
		d: {
			seat,
			hand_no: 1,
			prevailing: 'EAST',
			dealer: 0,
			turn: 0,
			phase: 'AWAIT_DRAW',
			own_hand: [1, 2, 3],
			concealed_counts: [13, 13, 13, 13],
			melds: [[], [], [], []],
			discard_pools: [[], [], [], []],
			flowers: [[], [], [], []],
			wall_remaining: 80,
			seat_status: ['connected', 'connected', 'connected', 'connected'],
			names: [null, null, null, null],
			host_seat: null,
			scores: [0, 0, 0, 0],
			legal_actions: [],
			claim_options: [],
			deadline_ts: null
		}
	};
}

describe('GameStore', () => {
	it('applies incoming events through the reducer, tracks seq/version/seat, and mirrors status', () => {
		const socket = new FakeSocket();
		const store = new GameStore(socket as unknown as MahjongSocket);

		expect(store.connection).toBe('idle');
		expect(store.seat).toBeNull();

		socket.emitStatus('open');
		expect(store.connection).toBe('open');

		socket.emit(stateSyncEvent(1, 12));

		expect(store.seat).toBe(1);
		expect(store.seq).toBe(12);
		expect(store.version).toBe(1);
		expect(store.state.ownHand).toEqual([1, 2, 3]);
		// the store feeds the socket back its own learned seat for future hello frames.
		expect(socket.setSeatCalls).toEqual([1]);

		store.destroy();
	});

	it('never mutates state outside of applying a real event (no optimistic writes)', () => {
		const socket = new FakeSocket();
		const store = new GameStore(socket as unknown as MahjongSocket);
		const before = store.state;

		// nothing sent yet -- state must be untouched.
		expect(store.state).toBe(before);
		expect(store.version).toBe(0);

		store.destroy();
	});

	it('surfaces an open claim window via claimOffer', () => {
		const socket = new FakeSocket();
		const store = new GameStore(socket as unknown as MahjongSocket);

		socket.emit({
			v: 1,
			ts: 1,
			seq: 1,
			t: 'claim_offer',
			d: { window_id: 9, options: [{ kind: 'pass' }], deadline_ts: 500 }
		});

		expect(store.claimOffer).toEqual({ windowId: 9, options: [{ kind: 'pass' }], deadlineTs: 500 });

		store.destroy();
	});

	it('destroy() unsubscribes from the socket', () => {
		const socket = new FakeSocket();
		const store = new GameStore(socket as unknown as MahjongSocket);
		expect(socket.listenerCount).toBeGreaterThan(0);

		store.destroy();
		expect(socket.listenerCount).toBe(0);

		const versionBefore = store.version;
		socket.emit(stateSyncEvent(0, 1));
		expect(store.version).toBe(versionBefore); // no longer listening
	});

	it('exposes the underlying socket for sending intents (store itself never sends)', () => {
		const socket = new FakeSocket();
		const store = new GameStore(socket as unknown as MahjongSocket);
		expect(store.socket).toBe(socket);
		store.destroy();
	});
});
