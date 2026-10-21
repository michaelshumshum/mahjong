// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Source of truth: server/app/protocol.py (docs/protocol.md §6).

export type ActionKind =
	| 'discard'
	| 'claim_chow'
	| 'claim_pung'
	| 'claim_kong'
	| 'claim_win'
	| 'pass'
	| 'declare_concealed_kong'
	| 'declare_added_kong'
	| 'declare_win';

export type BotTier = 'T0' | 'T1' | 'T2' | 'T4' | 'ORACLE';

export type ClaimChoice = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

export type ClaimKind = 'discard' | 'kong_rob';

export type ErrorCode =
	| 'bad_frame'
	| 'already_joined'
	| 'no_such_seat'
	| 'seat_taken'
	| 'bad_secret'
	| 'not_joined'
	| 'table_closed'
	| 'spectators_full';

export type HandOutcome = 'win' | 'exhaustive_draw';

export type MeldKind = 'chow' | 'pung' | 'exposed_kong' | 'concealed_kong' | 'added_kong' | 'pair';

export type Phase =
	| 'AWAIT_DRAW'
	| 'AWAIT_ACTION'
	| 'AWAIT_CLAIMS'
	| 'AWAIT_KONG_ROB'
	| 'SCORING'
	| 'HAND_OVER'
	| 'GAME_OVER';

export type Seat = 0 | 1 | 2 | 3;

export type SeatStatus = 'connected' | 'disconnected' | 'autoplay' | 'bot';

export type WinType = 'self_draw' | 'discard' | 'kong_rob' | 'flowers';

export type WindName = 'EAST' | 'SOUTH' | 'WEST' | 'NORTH';

export type WireSeatStatus = 'connected' | 'disconnected' | 'autoplay' | 'bot' | 'empty';

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
	choice: ClaimChoice;
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
	code: ErrorCode;
	message: string;
}

export interface StateSyncPayload {
	seat: Seat | null;
	hand_no: number;
	prevailing: WindName;
	dealer: Seat;
	turn: Seat;
	phase: Phase;
	own_hand: number[];
	concealed_counts: number[];
	melds: Record<string, unknown>[][];
	discard_pools: number[][];
	flowers: string[][];
	wall_remaining: number;
	seat_status: WireSeatStatus[];
	names: (string | null)[];
	scores: number[];
	legal_actions: Record<string, unknown>[];
	claim_options: Record<string, unknown>[];
	deadline_ts: number | null;
	host_seat: Seat | null;
	hands?: number[][] | null;
	hand_history?: HandHistoryEntryPayload[];
	ruleset_preset?: string | null;
	ruleset?: Record<string, unknown>;
	bot_levels?: (BotTier | null)[];
	seed_commit?: string | null;
}

export interface HandStartPayload {
	hand_no: number;
	prevailing: WindName;
	dealer: Seat;
	seats: WireSeatStatus[];
	seed_commit?: string | null;
}

export interface DealPayload {
	your_hand: number[];
	counts: Record<number, number>;
	flowers: string[][];
	wall_remaining: number;
}

export interface FlowerReplacePayload {
	seat: Seat;
	flower: string;
	replacement?: number | null;
}

export interface DrawPayload {
	seat: Seat;
	tile_id?: number | null;
}

export interface DiscardEventPayload {
	seat: Seat;
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
	claim_kind: ClaimKind;
	seat: Seat | null;
	action_kind: ActionKind | null;
}

export interface MeldPayload {
	seat: Seat;
	meld_kind: MeldKind;
	tiles: number[];
	from_seat?: Seat | null;
}

export interface KongReplacePayload {
	seat: Seat;
	tile_id?: number | null;
}

export interface TurnPayload {
	seat: Seat;
	phase: Phase;
	deadline_ts: number;
	legal?: Record<string, unknown>[] | null;
}

export interface HandEndPayload {
	hand_no: number;
	outcome: HandOutcome;
	winner: Seat | null;
	win_type: WinType | null;
	discarder: Seat | null;
	faan: number | null;
	faan_breakdown: Record<string, number> | null;
	points: number | null;
	payments: Record<number, number> | null;
	revealed: boolean;
	winning_hand: number[] | null;
	deadline_ts: number;
	fairness?: FairnessPayload | null;
}

export interface ScorePayload {
	totals: Record<number, number>;
}

export interface GameEndPayload {
	hand_no: number;
	scores: number[];
}

export interface SeatStatePayload {
	seat: Seat;
	status: SeatStatus;
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

export interface HandHistoryEntryPayload {
	hand_no: number;
	outcome: HandOutcome;
	winner: Seat | null;
	win_type: WinType | null;
	discarder: Seat | null;
	faan: number | null;
	faan_breakdown: Record<string, number> | null;
	points: number | null;
	payments: Record<number, number> | null;
	revealed: boolean;
	winning_hand: number[] | null;
	dealer: Seat;
	prevailing: WindName;
	winner_melds: Record<string, unknown>[] | null;
	fairness?: FairnessPayload | null;
}

export interface FairnessPayload {
	hand_seed: string;
	nonce: string;
}

/** Client -> server intents (docs/protocol.md §2). */
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
 * Server -> client events (docs/protocol.md §3). Keep the reducer's
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
