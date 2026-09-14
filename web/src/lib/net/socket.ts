import { env } from '$env/dynamic/public';
import type { Hello, Ping, ServerEvent } from './protocol';

const CLIENT_VERSION = '0.1.0';

function defaultWsUrl(): string {
	return env.PUBLIC_WS_URL || 'ws://localhost:8000/ws';
}

function nextId(): string {
	return `c-${crypto.randomUUID().slice(0, 8)}`;
}

function isServerEvent(msg: unknown): msg is ServerEvent {
	if (typeof msg !== 'object' || msg === null || !('t' in msg)) return false;
	const t = (msg as { t: unknown }).t;
	return t === 'pong' || t === 'error';
}

type Listener = (event: ServerEvent) => void;

/**
 * Thin WS client: connects, sends `hello` on open, exposes `ping()`, and
 * fans out parsed+validated server events to subscribers. No reducer/store
 * wiring here — callers decide what to do with events (see reducer.ts).
 */
export class MahjongSocket {
	#ws: WebSocket | null = null;
	#url: string;
	#listeners = new Set<Listener>();

	constructor(url: string = defaultWsUrl()) {
		this.#url = url;
	}

	get readyState(): number {
		return this.#ws?.readyState ?? WebSocket.CLOSED;
	}

	connect(): void {
		if (this.#ws) return;
		const ws = new WebSocket(this.#url);
		this.#ws = ws;

		ws.addEventListener('open', () => {
			this.#sendHello();
		});
		ws.addEventListener('message', (ev) => {
			this.#handleMessage(ev.data);
		});
		ws.addEventListener('close', () => {
			if (this.#ws === ws) this.#ws = null;
		});
	}

	disconnect(): void {
		this.#ws?.close();
		this.#ws = null;
	}

	/** Subscribe to parsed server events; returns an unsubscribe function. */
	onEvent(listener: Listener): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	ping(): void {
		const msg: Ping = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'ping',
			d: { t0: Date.now() }
		};
		this.#send(msg);
	}

	#sendHello(): void {
		const msg: Hello = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'hello',
			d: { client_version: CLIENT_VERSION }
		};
		this.#send(msg);
	}

	#send(msg: Hello | Ping): void {
		if (!this.#ws || this.#ws.readyState !== WebSocket.OPEN) return;
		this.#ws.send(JSON.stringify(msg));
	}

	#handleMessage(data: unknown): void {
		if (typeof data !== 'string') return;
		let parsed: unknown;
		try {
			parsed = JSON.parse(data);
		} catch {
			return;
		}
		if (!isServerEvent(parsed)) return;
		for (const listener of this.#listeners) listener(parsed);
	}
}
