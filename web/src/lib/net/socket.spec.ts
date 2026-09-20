import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { MahjongSocket } from './socket';
import type { Hello, Ping, Discard, Claim, Declare, Join } from './protocol';

type Listener = (ev: { data: string }) => void;

// Minimal fake matching the subset of the WebSocket API socket.ts uses:
// addEventListener('open'|'message'|'close'), send, close, readyState.
class FakeWebSocket {
	static CONNECTING = 0;
	static OPEN = 1;
	static CLOSING = 2;
	static CLOSED = 3;
	static instances: FakeWebSocket[] = [];

	readyState = FakeWebSocket.CONNECTING;
	sent: string[] = [];
	#listeners: Record<string, Listener[]> = {};

	constructor(public url: string) {
		FakeWebSocket.instances.push(this);
		// mirrors a real socket: OPEN arrives asynchronously after construction.
		queueMicrotask(() => {
			this.readyState = FakeWebSocket.OPEN;
			this.#emit('open', { data: '' });
		});
	}

	addEventListener(type: string, cb: Listener): void {
		(this.#listeners[type] ??= []).push(cb);
	}

	send(data: string): void {
		this.sent.push(data);
	}

	close(): void {
		this.readyState = FakeWebSocket.CLOSED;
		this.#emit('close', { data: '' });
	}

	simulateMessage(payload: unknown): void {
		this.#emit('message', { data: JSON.stringify(payload) });
	}

	#emit(type: string, ev: { data: string }): void {
		for (const l of this.#listeners[type] ?? []) l(ev);
	}
}

async function flushMicrotasks(): Promise<void> {
	await new Promise((resolve) => setTimeout(resolve, 0));
}

function sentMessages(ws: FakeWebSocket): unknown[] {
	return ws.sent.map((s) => JSON.parse(s));
}

beforeEach(() => {
	FakeWebSocket.instances = [];
	vi.stubGlobal('WebSocket', FakeWebSocket);
});

describe('MahjongSocket', () => {
	it('sends a hello envelope as soon as the socket opens', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		socket.connect();
		await flushMicrotasks();

		const ws = FakeWebSocket.instances[0];
		expect(ws.url).toBe('ws://test/ws');
		expect(ws.sent).toHaveLength(1);

		const hello = JSON.parse(ws.sent[0]) as Hello;
		expect(hello.v).toBe(1);
		expect(hello.t).toBe('hello');
		expect(hello.d.client_version).toBeTruthy();
		expect(typeof hello.id).toBe('string');
		// nothing known yet -- omitted, not sent as null (docs/02-protocol.md fairness-field
		// convention: "omit the key entirely", same rule applies to every optional wire field).
		expect(hello.d.last_seq).toBeUndefined();
		expect(hello.d.seat).toBeUndefined();
	});

	it('sends a typed ping envelope on demand', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		socket.connect();
		await flushMicrotasks();

		socket.ping();

		const ws = FakeWebSocket.instances[0];
		expect(ws.sent).toHaveLength(2); // hello, then ping
		const ping = JSON.parse(ws.sent[1]) as Ping;
		expect(ping.t).toBe('ping');
		expect(typeof ping.d.t0).toBe('number');
	});

	it('parses an incoming pong and delivers it to subscribers', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		const received: unknown[] = [];
		socket.onEvent((event) => received.push(event));
		socket.connect();
		await flushMicrotasks();

		const ws = FakeWebSocket.instances[0];
		ws.simulateMessage({ v: 1, ts: 123, seq: 1, t: 'pong', d: { t0: 10, t1: 20 } });

		expect(received).toEqual([{ v: 1, ts: 123, seq: 1, t: 'pong', d: { t0: 10, t1: 20 } }]);
	});

	it('ignores frames whose t is not a real server event', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		const received: unknown[] = [];
		socket.onEvent((event) => received.push(event));
		socket.connect();
		await flushMicrotasks();

		const ws = FakeWebSocket.instances[0];
		ws.simulateMessage('not json-shaped garbage that still parses, e.g. a bare string');
		ws.simulateMessage({ t: 'not_a_real_event', d: {} });

		expect(received).toEqual([]);
	});

	it('unsubscribe stops further delivery', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		const received: unknown[] = [];
		const unsubscribe = socket.onEvent((event) => received.push(event));
		socket.connect();
		await flushMicrotasks();

		unsubscribe();
		const ws = FakeWebSocket.instances[0];
		ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });

		expect(received).toEqual([]);
	});

	describe('client intents', () => {
		async function openSocket(): Promise<{ socket: MahjongSocket; ws: FakeWebSocket }> {
			const socket = new MahjongSocket('ws://test/ws');
			socket.connect();
			await flushMicrotasks();
			return { socket, ws: FakeWebSocket.instances[0] };
		}

		it('join sends {seat?} and omits seat for "first open seat"', async () => {
			const { socket, ws } = await openSocket();
			socket.join(2);
			socket.join();
			const [, first, second] = sentMessages(ws) as [unknown, Join, Join];
			expect(first.d).toEqual({ seat: 2 });
			expect(second.d).toEqual({});
		});

		it('join threads an optional name alongside seat', async () => {
			const { socket, ws } = await openSocket();
			socket.join(2, 'Alice');
			socket.join(undefined, 'Bob');
			const [, first, second] = sentMessages(ws) as [unknown, Join, Join];
			expect(first.d).toEqual({ seat: 2, name: 'Alice' });
			expect(second.d).toEqual({ name: 'Bob' });
		});

		it('discard sends {tile_id}', async () => {
			const { socket, ws } = await openSocket();
			socket.discard(47);
			const [, msg] = sentMessages(ws) as [unknown, Discard];
			expect(msg.t).toBe('discard');
			expect(msg.d).toEqual({ tile_id: 47 });
		});

		it('claim sends {window_id, choice, tiles?}', async () => {
			const { socket, ws } = await openSocket();
			socket.claim(204, 'chow', [4, 5]);
			socket.claim(205, 'pass');
			const [, first, second] = sentMessages(ws) as [unknown, Claim, Claim];
			expect(first.d).toEqual({ window_id: 204, choice: 'chow', tiles: [4, 5] });
			expect(second.d).toEqual({ window_id: 205, choice: 'pass' });
		});

		it('declare sends {kind, tiles?}, including the concealed/added kong convenience wrappers', async () => {
			const { socket, ws } = await openSocket();
			socket.declareWin();
			socket.declareConcealedKong([1, 1, 1, 1]);
			socket.declareAddedKong([2, 2, 2, 9]);
			const [, win, ck, ak] = sentMessages(ws) as [unknown, Declare, Declare, Declare];
			expect(win.d).toEqual({ kind: 'win' });
			expect(ck.d).toEqual({ kind: 'concealed_kong', tiles: [1, 1, 1, 1] });
			expect(ak.d).toEqual({ kind: 'added_kong', tiles: [2, 2, 2, 9] });
		});

		it('ready sends its documented payload', async () => {
			const { socket, ws } = await openSocket();
			socket.ready();
			const [, ready] = sentMessages(ws) as [unknown, { d: unknown }];
			expect(ready.d).toEqual({});
		});

		it('every client message carries a unique idempotency id', async () => {
			const { socket, ws } = await openSocket();
			socket.discard(1);
			socket.discard(2);
			const ids = sentMessages(ws).map((m) => (m as { id: string }).id);
			expect(new Set(ids).size).toBe(ids.length);
			for (const id of ids) expect(typeof id).toBe('string');
		});
	});

	describe('seq tracking and resync', () => {
		it('accepts a contiguous stream and forwards every frame', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			const received: unknown[] = [];
			socket.onEvent((event) => received.push(event));
			socket.connect();
			await flushMicrotasks();

			const ws = FakeWebSocket.instances[0];
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });
			ws.simulateMessage({ v: 1, ts: 2, seq: 2, t: 'pong', d: { t0: null, t1: 2 } });

			expect(received).toHaveLength(2);
			expect(socket.lastSeq).toBe(2);
			expect(socket.status).toBe('open');
		});

		it('a gap on this seat’s own stream is dropped, not forwarded, and triggers a resync hello', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			const received: unknown[] = [];
			socket.onEvent((event) => received.push(event));
			socket.connect();
			await flushMicrotasks();

			const ws = FakeWebSocket.instances[0];
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });
			expect(socket.lastSeq).toBe(1);

			// seq should be 2 next; 5 arrives instead -- a real gap.
			ws.simulateMessage({ v: 1, ts: 2, seq: 5, t: 'pong', d: { t0: null, t1: 5 } });

			// dropped, never silently patched over the missing frames:
			expect(received).toHaveLength(1);
			expect(socket.lastSeq).toBe(1);
			expect(socket.status).toBe('resyncing');

			// and a fresh hello carrying last_seq (+ seat, once known) was sent to ask the server
			// to fill the gap (docs/02-protocol.md §5's three-way hello{last_seq} branch).
			const messages = sentMessages(ws);
			const secondHello = messages.at(-1) as Hello;
			expect(secondHello.t).toBe('hello');
			expect(secondHello.d.last_seq).toBe(1);
		});

		it('a state_sync always resolves a resync regardless of its own seq value', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			const received: ServerEventLike[] = [];
			socket.onEvent((event) => received.push(event as ServerEventLike));
			socket.connect();
			await flushMicrotasks();

			const ws = FakeWebSocket.instances[0];
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });
			ws.simulateMessage({ v: 1, ts: 2, seq: 5, t: 'pong', d: { t0: null, t1: 5 } }); // gap
			expect(socket.status).toBe('resyncing');

			ws.simulateMessage({
				v: 1,
				ts: 3,
				seq: 40,
				t: 'state_sync',
				d: {
					seat: 0,
					hand_no: 1,
					prevailing: 'E',
					dealer: 0,
					turn: 0,
					phase: 'AWAIT_DRAW',
					own_hand: [],
					concealed_counts: [13, 13, 13, 13],
					melds: [[], [], [], []],
					discard_pools: [[], [], [], []],
					flowers: [[], [], [], []],
					wall_remaining: 80,
					seat_status: ['connected', 'connected', 'connected', 'connected'],
					scores: [0, 0, 0, 0],
					legal_actions: [],
					claim_options: [],
					deadline_ts: null
				}
			});

			expect(socket.status).toBe('open');
			expect(socket.lastSeq).toBe(40);
			expect(received.at(-1)?.t).toBe('state_sync');

			// stream resumes gapless checking from the new baseline:
			ws.simulateMessage({ v: 1, ts: 4, seq: 41, t: 'pong', d: { t0: null, t1: 41 } });
			expect(socket.lastSeq).toBe(41);
			expect(socket.status).toBe('open');
		});

		it('a stale/duplicate replayed frame is ignored, not treated as a new gap', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			const received: unknown[] = [];
			socket.onEvent((event) => received.push(event));
			socket.connect();
			await flushMicrotasks();

			const ws = FakeWebSocket.instances[0];
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });
			ws.simulateMessage({ v: 1, ts: 2, seq: 2, t: 'pong', d: { t0: null, t1: 2 } });
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } }); // duplicate

			expect(received).toHaveLength(2);
			expect(socket.lastSeq).toBe(2);
			expect(socket.status).toBe('open');
		});

		it('learns its own seat from a state_sync via setSeat, carried on the next hello', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			socket.connect();
			await flushMicrotasks();
			const ws = FakeWebSocket.instances[0];

			socket.setSeat(2);
			// force a resync so we can observe the next hello's contents.
			ws.simulateMessage({ v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: null, t1: 1 } });
			ws.simulateMessage({ v: 1, ts: 2, seq: 9, t: 'pong', d: { t0: null, t1: 9 } });

			const hello = sentMessages(ws).at(-1) as Hello;
			expect(hello.d.seat).toBe(2);
			expect(hello.d.last_seq).toBe(1);
		});
	});

	describe('reconnect', () => {
		beforeEach(() => {
			vi.useFakeTimers();
		});
		afterEach(() => {
			vi.useRealTimers();
		});

		it('an unexpected close schedules a reconnect that resumes from the last seq/seat', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			socket.connect();
			await vi.advanceTimersByTimeAsync(0); // flush the FakeWebSocket open microtask

			const ws1 = FakeWebSocket.instances[0];
			ws1.simulateMessage({ v: 1, ts: 1, seq: 7, t: 'pong', d: { t0: null, t1: 7 } });
			socket.setSeat(3);

			ws1.close(); // unexpected drop, not socket.disconnect()
			expect(socket.status).toBe('closed');

			await vi.advanceTimersByTimeAsync(400); // covers the first backoff step (250ms ± 20%)

			expect(FakeWebSocket.instances).toHaveLength(2);
			const ws2 = FakeWebSocket.instances[1];
			const hello = sentMessages(ws2)[0] as Hello;
			expect(hello.d.last_seq).toBe(7);
			expect(hello.d.seat).toBe(3);
		});

		it('disconnect() does not schedule a reconnect', async () => {
			const socket = new MahjongSocket('ws://test/ws');
			socket.connect();
			await vi.advanceTimersByTimeAsync(0);

			socket.disconnect();
			await vi.advanceTimersByTimeAsync(10000);

			expect(FakeWebSocket.instances).toHaveLength(1);
			expect(socket.status).toBe('closed');
		});
	});
});

// local minimal shape -- avoids importing the full ServerEvent union just to read `.t` in tests.
type ServerEventLike = { t: string };
