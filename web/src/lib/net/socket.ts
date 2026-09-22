import { env } from '$env/dynamic/public';
import type {
	Auto,
	AutoPayload,
	Claim,
	ClaimPayload,
	ClientMessage,
	Declare,
	DeclarePayload,
	Discard,
	HandEndAck,
	Hello,
	HelloPayload,
	Join,
	JoinPayload,
	Ping,
	Ready,
	ServerEvent,
	StartWithBots
} from './protocol';
import type { ConnectionStatus } from '../game/state';

const CLIENT_VERSION = '0.1.0';

/** Base WS URL, no query string -- callers append `?table=<id>` (docs/02-protocol.md's
 * `wss://…/ws?table={id}`, `app/ws.py`'s `table` query param). Exported for
 * `/table/[id]`'s live wiring, which needs the same base this module defaults to. */
export function defaultWsUrl(): string {
	return env.PUBLIC_WS_URL || 'ws://localhost:8000/ws';
}

function nextId(): string {
	return `c-${crypto.randomUUID().slice(0, 8)}`;
}

// Kept in sync by hand with protocol.d.ts's ServerEvent union (mirrors
// protocol.assertNever.ts's switch, generated from the same source) — a new server event type
// needs a case added there, which is exactly where a maintainer adding one will already be.
const SERVER_EVENT_TYPES = new Set<string>([
	'pong',
	'error',
	'state_sync',
	'hand_start',
	'deal',
	'flower_replace',
	'draw',
	'discard',
	'claim_offer',
	'claim_resolved',
	'meld',
	'kong_replace',
	'turn',
	'hand_end',
	'score',
	'game_end',
	'seat_state',
	'server_shutdown',
	'ack'
]);

function isServerEvent(msg: unknown): msg is ServerEvent {
	if (typeof msg !== 'object' || msg === null || !('t' in msg)) return false;
	return SERVER_EVENT_TYPES.has((msg as { t: unknown }).t as string);
}

type Listener = (event: ServerEvent) => void;
type StatusListener = (status: ConnectionStatus) => void;

export interface ResumeInfo {
	lastSeq?: number | null;
	seat?: number | null;
	secret?: string | null;
}

/**
 * WS client: connects, sends `hello` on open (carrying `last_seq`/`seat` when known, so a
 * reconnect or a caller-supplied resume point resumes rather than cold-starts —
 * docs/02-protocol.md §5), exposes every real client intent, and fans out parsed+validated
 * server events to subscribers. Enforces the one correctness rule that can't be deferred to
 * lib/game/store.svelte.ts: **seq is per-seat, gapless within this stream; a gap triggers a
 * resync (re-sending `hello{last_seq, seat}`), never a silent patch** (web/AGENTS.md). No
 * reducer/store wiring here — callers decide what to do with events (see reducer.ts).
 */
export class MahjongSocket {
	#ws: WebSocket | null = null;
	#url: string;
	#listeners = new Set<Listener>();
	#statusListeners = new Set<StatusListener>();

	#status: ConnectionStatus = 'idle';
	#lastSeq: number | null = null;
	#seat: number | null = null;
	#secret: string | null = null;

	#closedByUser = false;
	#reconnectAttempts = 0;
	#reconnectTimer: ReturnType<typeof setTimeout> | null = null;

	constructor(url: string = defaultWsUrl()) {
		this.#url = url;
	}

	get readyState(): number {
		return this.#ws?.readyState ?? WebSocket.CLOSED;
	}

	get status(): ConnectionStatus {
		return this.#status;
	}

	get lastSeq(): number | null {
		return this.#lastSeq;
	}

	get seat(): number | null {
		return this.#seat;
	}

	/** This seat's `reconnect_secret` (00-architecture.md §2.1), once its `join` ack has landed —
	 * `null` before then, or for a connection that's never joined a seat. Callers persist it
	 * (`lib/ui/settings-storage.ts`'s `saveSecretForTable`) so a later page load can feed it back
	 * in via `connect({seat, secret})`. */
	get secret(): string | null {
		return this.#secret;
	}

	/** Learn (or clear) this connection's own seat once the reducer sees it in a `state_sync`
	 * (StateSyncPayload.seat) — needed here so a later reconnect/resync `hello` can carry it. */
	setSeat(seat: number | null): void {
		this.#seat = seat;
	}

	/** `resume` seeds `last_seq`/`seat`/`secret` before the first `hello` of this call — the
	 * page-reload case, where a fresh `MahjongSocket` has no memory of a previous connection's
	 * stream. Omit it for a plain fresh connect, or to just resume whatever this instance already
	 * tracked itself (an unexpected mid-session close already resumes automatically — `#secret`
	 * is captured on the fly from `join`'s own ack, below). */
	connect(resume?: ResumeInfo): void {
		this.#closedByUser = false;
		if (resume) {
			if (resume.lastSeq !== undefined) this.#lastSeq = resume.lastSeq;
			if (resume.seat !== undefined) this.#seat = resume.seat;
			if (resume.secret !== undefined) this.#secret = resume.secret;
		}
		if (this.#reconnectTimer !== null) {
			clearTimeout(this.#reconnectTimer);
			this.#reconnectTimer = null;
		}
		this.#doConnect();
	}

	disconnect(): void {
		this.#closedByUser = true;
		if (this.#reconnectTimer !== null) {
			clearTimeout(this.#reconnectTimer);
			this.#reconnectTimer = null;
		}
		this.#ws?.close();
		this.#ws = null;
		this.#setStatus('closed');
	}

	/** Subscribe to parsed server events; returns an unsubscribe function. */
	onEvent(listener: Listener): () => void {
		this.#listeners.add(listener);
		return () => this.#listeners.delete(listener);
	}

	/** Subscribe to connection status changes; returns an unsubscribe function. */
	onStatus(listener: StatusListener): () => void {
		this.#statusListeners.add(listener);
		return () => this.#statusListeners.delete(listener);
	}

	ping(): void {
		const msg: Ping = { v: 1, id: nextId(), ts: Date.now(), t: 'ping', d: { t0: Date.now() } };
		this.#send(msg);
	}

	/** `name` (M5, docs/02-protocol.md §2) is a client-chosen guest display name, set once at
	 * join -- the server trims/caps/defaults it, so no client-side validation beyond what the
	 * caller already did (`lib/ui/settings-storage.ts`'s persisted value) is needed here. */
	join(seat?: number | null, name?: string | null): void {
		const d: JoinPayload = {};
		if (seat != null) d.seat = seat;
		if (name != null) d.name = name;
		const msg: Join = { v: 1, id: nextId(), ts: Date.now(), t: 'join', d };
		this.#send(msg);
	}

	ready(): void {
		const msg: Ready = { v: 1, id: nextId(), ts: Date.now(), t: 'ready', d: {} };
		this.#send(msg);
	}

	/** Host-only (`ClientGameState.hostSeat === state.seat`); the server rejects a non-host
	 * sender with `error:'not_host'` and a call once the table's already started with
	 * `error:'already_started'` -- this method sends unconditionally and lets the UI gate on
	 * `isHost`/`tableReady` instead of duplicating that check here. */
	startWithBots(): void {
		const msg: StartWithBots = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'start_with_bots',
			d: {}
		};
		this.#send(msg);
	}

	handEndAck(): void {
		const msg: HandEndAck = { v: 1, id: nextId(), ts: Date.now(), t: 'hand_end_ack', d: {} };
		this.#send(msg);
	}

	discard(tileId: number): void {
		const msg: Discard = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'discard',
			d: { tile_id: tileId }
		};
		this.#send(msg);
	}

	claim(windowId: number, choice: ClaimPayload['choice'], tiles?: number[] | null): void {
		const msg: Claim = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'claim',
			d: { window_id: windowId, choice, ...(tiles != null ? { tiles } : {}) }
		};
		this.#send(msg);
	}

	declare(kind: DeclarePayload['kind'], tiles?: number[] | null): void {
		const msg: Declare = {
			v: 1,
			id: nextId(),
			ts: Date.now(),
			t: 'declare',
			d: { kind, ...(tiles != null ? { tiles } : {}) }
		};
		this.#send(msg);
	}

	declareWin(): void {
		this.declare('win');
	}

	declareConcealedKong(tiles: number[]): void {
		this.declare('concealed_kong', tiles);
	}

	declareAddedKong(tiles: number[]): void {
		this.declare('added_kong', tiles);
	}

	auto(opts: AutoPayload): void {
		const msg: Auto = { v: 1, id: nextId(), ts: Date.now(), t: 'auto', d: opts };
		this.#send(msg);
	}

	#doConnect(): void {
		if (this.#ws) return;
		this.#setStatus('connecting');
		const ws = new WebSocket(this.#url);
		this.#ws = ws;

		ws.addEventListener('open', () => {
			this.#reconnectAttempts = 0;
			this.#setStatus('open');
			this.#sendHello();
		});
		ws.addEventListener('message', (ev) => {
			this.#handleMessage(ev.data);
		});
		ws.addEventListener('close', () => {
			if (this.#ws !== ws) return;
			this.#ws = null;
			this.#setStatus('closed');
			if (!this.#closedByUser) this.#scheduleReconnect();
		});
	}

	/** Exponential backoff with jitter, `min(250ms * 2^attempt, 10s) ± 20%`
	 * (docs/02-protocol.md §8). */
	#scheduleReconnect(): void {
		const attempt = this.#reconnectAttempts++;
		const base = Math.min(250 * 2 ** attempt, 10000);
		const delay = base * (0.8 + Math.random() * 0.4);
		this.#reconnectTimer = setTimeout(() => {
			this.#reconnectTimer = null;
			this.#doConnect();
		}, delay);
	}

	#sendHello(): void {
		const d: HelloPayload = { client_version: CLIENT_VERSION };
		if (this.#lastSeq !== null) d.last_seq = this.#lastSeq;
		if (this.#seat !== null) d.seat = this.#seat;
		if (this.#secret !== null) d.secret = this.#secret;
		const msg: Hello = { v: 1, id: nextId(), ts: Date.now(), t: 'hello', d };
		this.#send(msg);
	}

	/** Re-sends `hello{last_seq, seat}` on the live connection to ask the server to fill a
	 * detected gap — docs/02-protocol.md §5's three-way branch (replay / full `state_sync` /
	 * nothing missed) isn't reconnect-only; it's keyed only on what `last_seq` compares against
	 * the seat's buffered stream, so re-asking mid-connection is the same request. */
	#requestResync(): void {
		if (this.#status === 'resyncing') return; // already asked; wait for the reply
		this.#setStatus('resyncing');
		this.#sendHello();
	}

	#send(msg: ClientMessage): void {
		if (!this.#ws || this.#ws.readyState !== WebSocket.OPEN) return;
		this.#ws.send(JSON.stringify(msg));
	}

	#setStatus(status: ConnectionStatus): void {
		if (this.#status === status) return;
		this.#status = status;
		for (const listener of this.#statusListeners) listener(status);
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
		this.#ingest(parsed);
	}

	/** Per-seat seq gap detection (web/AGENTS.md, docs/02-protocol.md §1/§5). `state_sync` is
	 * always accepted as a full replace regardless of seq continuity — it *is* the resync
	 * mechanism. Any other frame with `seq > lastSeq + 1` is a gap: dropped, never forwarded to
	 * listeners (applying it out of order could corrupt client state), and triggers a resync. A
	 * frame with `seq <= lastSeq` is a stale replay duplicate and is silently ignored. */
	#ingest(event: ServerEvent): void {
		const seq = typeof event.seq === 'number' ? event.seq : null;

		// `join`'s own ack carries this seat's one-time reconnect credential
		// (00-architecture.md §2.1) — captured here, not just left for a caller to persist, so
		// this same socket instance can already present it on a later automatic reconnect
		// (`#scheduleReconnect` → `#doConnect` → `#sendHello`) within this page's lifetime,
		// same as `#lastSeq` self-tracks. `saveSecretForTable` (settings-storage.ts) is a
		// separate, caller-driven step for surviving a page reload.
		if (event.t === 'ack' && event.d.reconnect_secret != null) {
			this.#secret = event.d.reconnect_secret;
		}

		if (event.t === 'state_sync') {
			if (seq !== null) this.#lastSeq = seq;
			this.#setStatus('open');
			this.#dispatch(event);
			return;
		}

		if (seq === null) {
			this.#dispatch(event);
			return;
		}

		if (this.#lastSeq === null || seq === this.#lastSeq + 1) {
			this.#lastSeq = seq;
			this.#setStatus('open');
			this.#dispatch(event);
			return;
		}

		if (seq <= this.#lastSeq) {
			return; // already applied — a replay/backpressure duplicate
		}

		this.#requestResync();
	}

	#dispatch(event: ServerEvent): void {
		for (const listener of this.#listeners) listener(event);
	}
}
