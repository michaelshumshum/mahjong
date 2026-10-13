// plain data, no runes -- store.svelte.ts wraps this in `$state`, so reducer.spec.ts can test
// transitions with no Svelte compile step. Field names camelCase the wire; protocol.d.ts stays snake_case.

import type { RuleSet } from '$lib/net/ruleset';

export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'resyncing' | 'closed';

/** A live claim offer, or the options embedded in a `state_sync` snapshot — the latter has no
 * `window_id` on the wire, so `windowId` stays `null` until a real `claim_offer` supplies one. */
export interface ClaimWindowState {
	windowId: number | null;
	options: Record<string, unknown>[];
	deadlineTs: number | null;
}

export interface MeldState {
	kind: string;
	tiles: number[] | null; // null only for another seat's still-concealed concealed_kong
	count: number | null;
	fromSeat: number | null;
}

/** A provable-fairness reveal. `commit` is the `hand_start.seed_commit` this session saw live;
 * `null` for a hand only known from `state_sync.hand_history`. */
export interface FairnessState {
	handSeed: string;
	nonce: string;
	commit: string | null;
}

export interface HandEndState {
	handNo: number;
	outcome: string;
	winner: number | null;
	winType: string | null;
	discarder: number | null;
	faan: number | null;
	faanBreakdown: Record<string, number> | null;
	points: number | null;
	payments: Record<number, number> | null;
	revealed: boolean;
	winningHand: number[] | null;
	/** `provable_fairness` tables only. */
	fairness?: FairnessState | null;
}

export interface GameEndState {
	handNo: number;
	scores: number[];
}

/** One completed hand. `dealer`/`prevailing` aren't on `hand_end`'s own payload — captured off
 * `ClientGameState` when the reducer sees the event, since only `hand_start` changes them. */
export interface HandHistoryEntry extends HandEndState {
	dealer: number;
	prevailing: string;
	/** Winner's `melds` snapshotted at `hand_end` (`null` for a non-win outcome) — `state.melds`
	 * resets on the next `hand_start`, so this is the only place a past round's melds survive. */
	winnerMelds: MeldState[] | null;
}

export interface ClientGameState {
	seat: number | null;
	handNo: number;
	prevailing: string;
	dealer: number;
	turn: number;
	phase: string;
	ownHand: number[];
	/** tile_id held apart from the sorted hand, physical-play style (docs/frontend.md §1).
	 * `null` after a claimed chow/pung/kong too — a claim never leaves a spare tile to hold apart. */
	drawnTileId: number | null;
	concealedCounts: number[];
	/** Every seat's concealed tile_ids, spectator-of-open-hands-table only; `null` otherwise. */
	hands: number[][] | null;
	melds: MeldState[][];
	discardPools: number[][];
	flowers: string[][];
	wallRemaining: number;
	seatStatus: string[];
	/** Each seat's resolved guest display name; `null` for an `empty` seat. */
	names: (string | null)[];
	/** Each `bot` seat's tier (`T1`/`T2`/`T4`/`ORACLE`); `null` for every other seat. */
	botLevels: (string | null)[];
	/** Whichever seat's `join` was this table's first. Never changes for the life of the table. */
	hostSeat: number | null;
	/** This table's ruleset, fixed at construction; `null` until the first `state_sync` lands.
	 * `rulesetPreset` is the matching `RULESET_PRESETS` key, `null` for a custom ruleset. */
	ruleset: RuleSet | null;
	rulesetPreset: string | null;
	/** Current hand's `seed_commit` on a `provable_fairness` table, else `null`. */
	seedCommit: string | null;
	scores: number[];
	legalActions: Record<string, unknown>[];
	deadlineTs: number | null;
	claimOffer: ClaimWindowState | null;
	/** Last `discard` seen — `claim_offer` itself carries no tile/seat, so this plus `turn`
	 * (which still names the discarder) is what a live claim window shows as "being claimed". */
	lastDiscard: { seat: number; tileId: number } | null;
	lastHandEnd: HandEndState | null;
	/** Hand-end hold deadline: open until every seat acks or this elapses. Set by `hand_end`,
	 * cleared by the next `hand_start`. */
	handEndDeadlineTs: number | null;
	/** Every completed hand, oldest first -- unlike `lastHandEnd` (latest only). Grown by live
	 * `hand_end` plus `state_sync.hand_history` backfill (`mergeHandHistory` in reducer.ts). */
	handHistory: HandHistoryEntry[];
	gameEnd: GameEndState | null;
	shutdownDeadlineTs: number | null;
}

export function initialClientGameState(): ClientGameState {
	return {
		seat: null,
		handNo: 0,
		prevailing: '',
		dealer: 0,
		turn: 0,
		phase: 'IDLE',
		ownHand: [],
		drawnTileId: null,
		concealedCounts: [0, 0, 0, 0],
		hands: null,
		melds: [[], [], [], []],
		discardPools: [[], [], [], []],
		flowers: [[], [], [], []],
		wallRemaining: 0,
		seatStatus: ['disconnected', 'disconnected', 'disconnected', 'disconnected'],
		names: [null, null, null, null],
		botLevels: [null, null, null, null],
		hostSeat: null,
		ruleset: null,
		rulesetPreset: null,
		seedCommit: null,
		scores: [0, 0, 0, 0],
		legalActions: [],
		deadlineTs: null,
		claimOffer: null,
		lastDiscard: null,
		lastHandEnd: null,
		handEndDeadlineTs: null,
		handHistory: [],
		gameEnd: null,
		shutdownDeadlineTs: null
	};
}
