import { describe, it, expect, beforeEach, vi } from 'vitest';
import { MahjongSocket } from './socket';
import type { Hello, Ping } from './protocol';

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

	it('ignores frames that are not modeled server events', async () => {
		const socket = new MahjongSocket('ws://test/ws');
		const received: unknown[] = [];
		socket.onEvent((event) => received.push(event));
		socket.connect();
		await flushMicrotasks();

		const ws = FakeWebSocket.instances[0];
		ws.simulateMessage('not json-shaped garbage that still parses, e.g. a bare string');
		ws.simulateMessage({ t: 'ack', d: { id: 'c-1', ok: true } });

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
});
