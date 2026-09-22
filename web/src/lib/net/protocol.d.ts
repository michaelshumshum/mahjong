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

export interface Join extends Envelope {
	t: 'join';
	d: JoinPayload;
}

export interface Ready extends Envelope {
	t: 'ready';
	d: ReadyPayload;
}

export interface StartWithBots extends Envelope {
	t: 'start_with_bots';
	d: StartWithBotsPayload;
}

export interface Discard extends Envelope {
	t: 'discard';
	d: DiscardPayload;
}

export interface Claim extends Envelope {
	t: 'claim';
	d: ClaimPayload;
}

export interface Declare extends Envelope {
	t: 'declare';
	d: DeclarePayload;
}

export interface Auto extends Envelope {
	t: 'auto';
	d: AutoPayload;
}

export interface HandEndAck extends Envelope {
	t: 'hand_end_ack';
	d: HandEndAckPayload;
}

export interface Pong extends Envelope {
	t: 'pong';
	d: PongPayload;
}

export interface ErrorEvent extends Envelope {
	t: 'error';
	d: ErrorPayload;
}

export interface StateSync extends Envelope {
	t: 'state_sync';
	d: StateSyncPayload;
}

export interface HandStart extends Envelope {
	t: 'hand_start';
	d: HandStartPayload;
}

export interface Deal extends Envelope {
	t: 'deal';
	d: DealPayload;
}

export interface FlowerReplace extends Envelope {
	t: 'flower_replace';
	d: FlowerReplacePayload;
}

export interface Draw extends Envelope {
	t: 'draw';
	d: DrawPayload;
}

export interface DiscardEvent extends Envelope {
	t: 'discard';
	d: DiscardEventPayload;
}

export interface ClaimOffer extends Envelope {
	t: 'claim_offer';
	d: ClaimOfferPayload;
}

export interface ClaimResolved extends Envelope {
	t: 'claim_resolved';
	d: ClaimResolvedPayload;
}

export interface Meld extends Envelope {
	t: 'meld';
	d: MeldPayload;
}

export interface KongReplace extends Envelope {
	t: 'kong_replace';
	d: KongReplacePayload;
}

export interface Turn extends Envelope {
	t: 'turn';
	d: TurnPayload;
}

export interface HandEnd extends Envelope {
	t: 'hand_end';
	d: HandEndPayload;
}

export interface Score extends Envelope {
	t: 'score';
	d: ScorePayload;
}

export interface GameEnd extends Envelope {
	t: 'game_end';
	d: GameEndPayload;
}

export interface SeatState extends Envelope {
	t: 'seat_state';
	d: SeatStatePayload;
}

export interface ServerShutdown extends Envelope {
	t: 'server_shutdown';
	d: ServerShutdownPayload;
}

export interface Ack extends Envelope {
	t: 'ack';
	d: AckPayload;
}

export interface HelloPayload {
	last_seq?: number | null;
	client_version: string;
	seat?: number | null;
	secret?: string | null;
}

export interface PingPayload {
	t0: number;
}

export interface JoinPayload {
	seat?: number | null;
	name?: string | null;
}

export interface ReadyPayload {}

export interface StartWithBotsPayload {}

export interface DiscardPayload {
	tile_id: number;
}

export interface ClaimPayload {
	window_id: number;
	choice: 'pass' | 'chow' | 'pung' | 'kong' | 'win';
	tiles?: number[] | null;
}

export interface DeclarePayload {
	kind: 'concealed_kong' | 'added_kong' | 'win';
	tiles?: number[] | null;
}

export interface AutoPayload {
	no_calls?: boolean | null;
	auto_pass_chow?: boolean | null;
}

export interface HandEndAckPayload {}

export interface PongPayload {
	t0?: number | null;
	t1: number;
}

export interface ErrorPayload {
	code: string;
	message: string;
}

export interface StateSyncPayload {
	seat: number | null;
	hand_no: number;
	prevailing: string;
	dealer: number;
	turn: number;
	phase: string;
	own_hand: number[];
	concealed_counts: number[];
	melds: Record<string, unknown>[][];
	discard_pools: number[][];
	flowers: string[][];
	wall_remaining: number;
	seat_status: string[];
	names: (string | null)[];
	scores: number[];
	legal_actions: Record<string, unknown>[];
	claim_options: Record<string, unknown>[];
	deadline_ts: number | null;
	host_seat: number | null;
	hands?: number[][] | null;
}

export interface HandStartPayload {
	hand_no: number;
	prevailing: string;
	dealer: number;
	seats: string[];
}

export interface DealPayload {
	your_hand: number[];
	counts: Record<number, number>;
	wall_remaining: number;
}

export interface FlowerReplacePayload {
	seat: number;
	flower: string;
	replacement?: number | null;
}

export interface DrawPayload {
	seat: number;
	tile_id?: number | null;
}

export interface DiscardEventPayload {
	seat: number;
	tile_id: number;
	tile: string;
	pool_index: number;
}

export interface ClaimOfferPayload {
	window_id: number;
	options: Record<string, unknown>[];
	deadline_ts: number;
}

export interface ClaimResolvedPayload {
	window_id: number;
	claim_kind: string;
	seat: number | null;
	action_kind: string | null;
}

export interface MeldPayload {
	seat: number;
	meld_kind: string;
	tiles: number[] | null;
	count?: number | null;
	from_seat?: number | null;
}

export interface KongReplacePayload {
	seat: number;
	tile_id?: number | null;
}

export interface TurnPayload {
	seat: number;
	phase: string;
	deadline_ts: number;
	legal?: Record<string, unknown>[] | null;
}

export interface HandEndPayload {
	hand_no: number;
	outcome: string;
	winner: number | null;
	win_type: string | null;
	discarder: number | null;
	faan: number | null;
	faan_breakdown: Record<string, number> | null;
	points: number | null;
	payments: Record<number, number> | null;
	revealed: boolean;
	winning_hand: number[] | null;
	deadline_ts: number;
}

export interface ScorePayload {
	totals: Record<number, number>;
}

export interface GameEndPayload {
	hand_no: number;
	scores: number[];
}

export interface SeatStatePayload {
	seat: number;
	status: 'connected' | 'disconnected' | 'autoplay' | 'bot';
	name?: string | null;
}

export interface ServerShutdownPayload {
	deadline_ts: number;
}

export interface AckPayload {
	id: string;
	ok: boolean;
	error?: string | null;
	reconnect_secret?: string | null;
}

/** Client -> server intents (docs/02-protocol.md §2). */
export type ClientMessage =
	| Hello
	| Ping
	| Join
	| Ready
	| StartWithBots
	| Discard
	| Claim
	| Declare
	| Auto
	| HandEndAck;

/**
 * Server -> client events (docs/02-protocol.md §3). Keep the reducer's
 * switch over this type exhaustive (assertNever, protocol.assertNever.ts)
 * so a new member fails the build.
 */
export type ServerEvent =
	| Pong
	| ErrorEvent
	| StateSync
	| HandStart
	| Deal
	| FlowerReplace
	| Draw
	| DiscardEvent
	| ClaimOffer
	| ClaimResolved
	| Meld
	| KongReplace
	| Turn
	| HandEnd
	| Score
	| GameEnd
	| SeatState
	| ServerShutdown
	| Ack;

/** Mirrors protocol.py's AnyMessage — both directions, e.g. for a WS test harness. */
export type AnyMessage =
	| Hello
	| Ping
	| Join
	| Ready
	| StartWithBots
	| Discard
	| Claim
	| Declare
	| Auto
	| HandEndAck
	| Pong
	| ErrorEvent
	| StateSync
	| HandStart
	| Deal
	| FlowerReplace
	| Draw
	| DiscardEvent
	| ClaimOffer
	| ClaimResolved
	| Meld
	| KongReplace
	| Turn
	| HandEnd
	| Score
	| GameEnd
	| SeatState
	| ServerShutdown
	| Ack;
