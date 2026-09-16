import type { ServerEvent } from './protocol';
import { type ClientGameState, type MeldState } from '../game/state';

function assertNever(x: never): never {
	throw new Error(`unhandled: ${JSON.stringify(x)}`);
}

function replaceAt<T>(arr: readonly T[], index: number, value: T): T[] {
	const next = arr.slice();
	next[index] = value;
	return next;
}

function countsFromWire(counts: Record<number, number>): number[] {
	const next = [0, 0, 0, 0];
	for (const [seat, count] of Object.entries(counts)) next[Number(seat)] = count;
	return next;
}

function removeOne(hand: readonly number[], tileId: number): number[] {
	const idx = hand.indexOf(tileId);
	if (idx === -1) return hand.slice();
	const next = hand.slice();
	next.splice(idx, 1);
	return next;
}

function removeMany(hand: readonly number[], tileIds: readonly number[]): number[] {
	let next = hand.slice();
	for (const id of tileIds) next = removeOne(next, id);
	return next;
}

/** `state_sync.melds[seat][i]` (`app/views.py`'s `_meld_wire`) keys the meld kind as `kind`;
 * the live `meld` event (`MeldPayload`) keys it as `meld_kind`. Two different upstream
 * serializers for the same concept — see `views.py`'s `_meld_wire` vs `_build_event_wire`. */
function mapMeldDict(m: Record<string, unknown>): MeldState {
	return {
		kind: (m.kind ?? m.meld_kind) as string,
		tiles: (m.tiles as number[] | null | undefined) ?? null,
		count: (m.count as number | null | undefined) ?? null,
		fromSeat: (m.from_seat as number | null | undefined) ?? null
	};
}

/**
 * Pure reducer: server event -> next `ClientGameState` (docs/03-frontend.md §6). One
 * exhaustive switch over the real `ServerEvent` union — `assertNever` fails the build if
 * `protocol.d.ts` grows a member this doesn't handle. No side effects; `lib/game/store.svelte.ts`
 * is the only caller that mutates observable (`$state`) storage, by reassigning its `state`
 * field to this function's return value.
 */
export function reduce(state: ClientGameState, event: ServerEvent): ClientGameState {
	switch (event.t) {
		case 'pong':
			return state;

		case 'error':
			console.error('[reducer] server error', event.d.code, event.d.message);
			return state;

		case 'ack':
			// sender-only bookkeeping (docs/02-protocol.md §3) — no game-truth change.
			return state;

		case 'state_sync': {
			const d = event.d;
			return {
				...state,
				seat: d.seat,
				handNo: d.hand_no,
				prevailing: d.prevailing,
				dealer: d.dealer,
				turn: d.turn,
				phase: d.phase,
				ownHand: d.own_hand.slice(),
				concealedCounts: d.concealed_counts.slice(),
				melds: d.melds.map((seatMelds) => seatMelds.map(mapMeldDict)),
				discardPools: d.discard_pools.map((pool) => pool.slice()),
				flowers: d.flowers.map((fl) => fl.slice()),
				wallRemaining: d.wall_remaining,
				seatStatus: d.seat_status.slice(),
				scores: d.scores.slice(),
				legalActions: d.legal_actions,
				deadlineTs: d.deadline_ts,
				claimOffer:
					d.claim_options.length > 0
						? { windowId: null, options: d.claim_options, deadlineTs: d.deadline_ts }
						: null
			};
		}

		case 'hand_start': {
			const d = event.d;
			return {
				...state,
				handNo: d.hand_no,
				prevailing: d.prevailing,
				dealer: d.dealer,
				seatStatus: d.seats.slice(),
				ownHand: [],
				concealedCounts: [0, 0, 0, 0],
				melds: [[], [], [], []],
				discardPools: [[], [], [], []],
				flowers: [[], [], [], []],
				claimOffer: null,
				legalActions: [],
				deadlineTs: null,
				lastHandEnd: null
			};
		}

		case 'deal': {
			const d = event.d;
			return {
				...state,
				ownHand: d.your_hand.slice(),
				concealedCounts: countsFromWire(d.counts),
				wallRemaining: d.wall_remaining
			};
		}

		case 'flower_replace': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			return {
				...state,
				flowers: replaceAt(state.flowers, d.seat, [...state.flowers[d.seat], d.flower]),
				ownHand: isOwn && d.replacement != null ? [...state.ownHand, d.replacement] : state.ownHand
			};
		}

		case 'draw': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			return {
				...state,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					state.concealedCounts[d.seat] + 1
				),
				ownHand: isOwn && d.tile_id != null ? [...state.ownHand, d.tile_id] : state.ownHand
			};
		}

		case 'discard': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			const pool = state.discardPools[d.seat].slice();
			pool[d.pool_index] = d.tile_id;
			return {
				...state,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					Math.max(0, state.concealedCounts[d.seat] - 1)
				),
				ownHand: isOwn ? removeOne(state.ownHand, d.tile_id) : state.ownHand,
				// a discard claimed later in the same server-side reduce() is removed from the
				// discarder's pool server-side (docs/02-protocol.md §3); this client-side pool can
				// transiently show it until the next state_sync corrects it — not attempted here.
				discardPools: replaceAt(state.discardPools, d.seat, pool)
			};
		}

		case 'claim_offer': {
			const d = event.d;
			return {
				...state,
				claimOffer: { windowId: d.window_id, options: d.options, deadlineTs: d.deadline_ts }
			};
		}

		case 'claim_resolved': {
			const d = event.d;
			// a fresh window_id always fully replaces the previous set (docs/03-frontend.md §5);
			// a resolution for a window we've already moved past is stale and changes nothing.
			if (state.claimOffer && state.claimOffer.windowId !== d.window_id) return state;
			return { ...state, claimOffer: null };
		}

		case 'meld': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			const newMeld: MeldState = {
				kind: d.meld_kind,
				tiles: d.tiles,
				count: d.count ?? null,
				fromSeat: d.from_seat ?? null
			};

			if (d.meld_kind === 'added_kong') {
				// upgrades an existing pung already in melds[seat] -- replace it in place rather
				// than appending a second, now-stale entry for the same 3 tiles.
				const claimTiles = d.tiles ?? [];
				const seatMelds = state.melds[d.seat];
				const pungIdx = seatMelds.findIndex(
					(existing) =>
						existing.kind === 'pung' &&
						existing.tiles !== null &&
						existing.tiles.every((t) => claimTiles.includes(t))
				);
				const nextSeatMelds =
					pungIdx === -1 ? [...seatMelds, newMeld] : replaceAt(seatMelds, pungIdx, newMeld);
				const oldPungTiles = pungIdx === -1 ? [] : (seatMelds[pungIdx].tiles ?? []);
				const addedTile = claimTiles.find((t) => !oldPungTiles.includes(t));
				return {
					...state,
					melds: replaceAt(state.melds, d.seat, nextSeatMelds),
					concealedCounts: replaceAt(
						state.concealedCounts,
						d.seat,
						Math.max(0, state.concealedCounts[d.seat] - 1)
					),
					ownHand:
						isOwn && addedTile !== undefined ? removeOne(state.ownHand, addedTile) : state.ownHand
				};
			}

			const melds = replaceAt(state.melds, d.seat, [...state.melds[d.seat], newMeld]);

			if (d.meld_kind === 'concealed_kong') {
				return {
					...state,
					melds,
					concealedCounts: replaceAt(
						state.concealedCounts,
						d.seat,
						Math.max(0, state.concealedCounts[d.seat] - 4)
					),
					ownHand: isOwn && d.tiles ? removeMany(state.ownHand, d.tiles) : state.ownHand
				};
			}

			// chow/pung/exposed_kong: fully public (docs/02-protocol.md §3). `from_seat` set means
			// exactly one tile of `tiles` came from that seat's discard; the rest from this seat's
			// own concealed hand.
			const claimedCount = d.from_seat != null && d.tiles ? 1 : 0;
			const fromHandCount = (d.tiles?.length ?? 0) - claimedCount;
			return {
				...state,
				melds,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					Math.max(0, state.concealedCounts[d.seat] - fromHandCount)
				),
				ownHand: isOwn && d.tiles ? removeMany(state.ownHand, d.tiles) : state.ownHand
			};
		}

		case 'kong_replace': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			return {
				...state,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					state.concealedCounts[d.seat] + 1
				),
				ownHand: isOwn && d.tile_id != null ? [...state.ownHand, d.tile_id] : state.ownHand
			};
		}

		case 'turn': {
			const d = event.d;
			return {
				...state,
				turn: d.seat,
				phase: d.phase,
				deadlineTs: d.deadline_ts,
				legalActions: d.legal ?? [],
				claimOffer: null
			};
		}

		case 'hand_end': {
			const d = event.d;
			return {
				...state,
				lastHandEnd: {
					handNo: d.hand_no,
					outcome: d.outcome,
					winner: d.winner,
					winType: d.win_type,
					discarder: d.discarder,
					faan: d.faan,
					faanBreakdown: d.faan_breakdown,
					points: d.points,
					payments: d.payments,
					revealed: d.revealed,
					winningHand: d.winning_hand
				},
				claimOffer: null,
				legalActions: [],
				deadlineTs: null
			};
		}

		case 'score':
			return { ...state, scores: countsFromWire(event.d.totals) };

		case 'game_end': {
			const d = event.d;
			return {
				...state,
				gameEnd: { handNo: d.hand_no, scores: d.scores.slice() },
				scores: d.scores.slice()
			};
		}

		case 'seat_state': {
			const d = event.d;
			return { ...state, seatStatus: replaceAt(state.seatStatus, d.seat, d.status) };
		}

		case 'server_shutdown':
			return { ...state, shutdownDeadlineTs: event.d.deadline_ts };

		default:
			return assertNever(event);
	}
}
