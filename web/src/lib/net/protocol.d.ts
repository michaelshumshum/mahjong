// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Source of truth: server/app/protocol.py (docs/02-protocol.md §6).

export interface Envelope {
	v: 1;
	seq?: number | null;
	id?: string | null;
	ts: number;
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

export interface ErrorEvent extends Envelope {
	t: 'error';
	d: ErrorPayload;
}

export interface HelloPayload {
	last_seq?: number | null;
	client_version: string;
}

export interface PingPayload {
	t0: number;
}

export interface PongPayload {
	t0?: number | null;
	t1: number;
}

export interface ErrorPayload {
	code: string;
	message: string;
}

/** Client -> server intents (docs/02-protocol.md §2). */
export type ClientMessage = Hello | Ping;

/**
 * Server -> client events (docs/02-protocol.md §3). Keep the reducer's
 * switch over this type exhaustive (assertNever, protocol.assertNever.ts)
 * so a new member fails the build.
 */
export type ServerEvent = Pong | ErrorEvent;

/** Mirrors protocol.py's AnyMessage — both directions, e.g. for a WS test harness. */
export type AnyMessage = Hello | Ping | Pong | ErrorEvent;
