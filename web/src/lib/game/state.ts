// Pure client-side game state shape (docs/03-frontend.md §6), built incrementally by
// lib/net/reducer.ts from the real ServerEvent stream (protocol.d.ts). No Svelte/runes here —
// store.svelte.ts wraps this in `$state`; this module stays plain data + a factory so
// lib/net/reducer.spec.ts can test state transitions without a Svelte compile step.
//
// Field names mirror the wire payloads 1:1 (StateSyncPayload above all), camelCased per this
// codebase's hand-written-TS convention — protocol.d.ts itself stays snake_case because it's
// generated straight from the Python wire models (see that file's own header).

export type ConnectionStatus = 'idle' | 'connecting' | 'open' | 'resyncing' | 'closed';

/** A live claim offer (from `claim_offer`) or the claim options embedded in a `state_sync`
 * snapshot — the latter has no `window_id` on the wire (StateSyncPayload has no such field),
 * so `windowId` is `null` until the next real `claim_offer` event supplies one. */
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
}

export interface GameEndState {
	handNo: number;
	scores: number[];
}

export interface ClientGameState {
	seat: number | null;
	handNo: number;
	prevailing: string;
	dealer: number;
	turn: number;
	phase: string;
	ownHand: number[];
	concealedCounts: number[];
	melds: MeldState[][];
	discardPools: number[][];
	flowers: string[][];
	wallRemaining: number;
	seatStatus: string[];
	scores: number[];
	legalActions: Record<string, unknown>[];
	deadlineTs: number | null;
	claimOffer: ClaimWindowState | null;
	lastHandEnd: HandEndState | null;
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
		concealedCounts: [0, 0, 0, 0],
		melds: [[], [], [], []],
		discardPools: [[], [], [], []],
		flowers: [[], [], [], []],
		wallRemaining: 0,
		seatStatus: ['disconnected', 'disconnected', 'disconnected', 'disconnected'],
		scores: [0, 0, 0, 0],
		legalActions: [],
		deadlineTs: null,
		claimOffer: null,
		lastHandEnd: null,
		gameEnd: null,
		shutdownDeadlineTs: null
	};
}
