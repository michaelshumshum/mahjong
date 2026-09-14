// TEMPORARY hand-written stub — will be replaced by codegen from server/app/protocol.py (make proto), a later sub-task.

/** Common frame fields (docs/02-protocol.md §1). `t` and `d` are added by each concrete message. */
export interface Envelope {
	v: 1;
	/** server->client only: per-seat, dense, gapless. */
	seq?: number | null;
	/** client->server only: idempotency key. */
	id?: string | null;
	/** server clock, ms. */
	ts: number;
}

export interface HelloPayload {
	last_seq?: number | null;
	client_version: string;
}

export interface PingPayload {
	t0: number;
}

export interface PongPayload {
	/** null on an unsolicited keepalive pong (§8). */
	t0: number | null;
	t1: number;
}

export interface Hello extends Envelope {
	t: 'hello';
	d: HelloPayload;
}

export interface Ping extends Envelope {
	t: 'ping';
	d: PingPayload;
}

export interface Pong extends Envelope {
	t: 'pong';
	d: PongPayload;
}

export interface ErrorPayload {
	code: string;
	message: string;
}

// named ErrorEvent, not Error, so importing it doesn't shadow the global Error constructor.
export interface ErrorEvent extends Envelope {
	t: 'error';
	d: ErrorPayload;
}

/** Client -> server intents modeled so far. */
export type ClientMessage = Hello | Ping;

/**
 * Server -> client events modeled so far (`pong`, `error`) — grows as more of
 * protocol.py's AnyMessage union lands. Keep the reducer's switch over this
 * type exhaustive (assertNever) so a new member fails the build.
 */
export type ServerEvent = Pong | ErrorEvent;

/** Mirrors protocol.py's AnyMessage — one union for both directions until each side has enough members to split. */
export type AnyMessage = Hello | Ping | Pong | ErrorEvent;
