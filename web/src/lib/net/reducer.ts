import type { HandHistoryEntryPayload, ServerEvent } from './protocol';
import { type ClientGameState, type HandHistoryEntry, type MeldState } from '../game/state';

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

/** `ClientGameState.hands` update for one seat — a no-op when this isn't an open-hands view. */
function updateHand(
	hands: number[][] | null,
	seat: number,
	update: (hand: number[]) => number[]
): number[][] | null {
	return hands === null ? null : replaceAt(hands, seat, update(hands[seat]));
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

/** `state_sync.hand_history[i]` (`app/views.py`'s `hand_history_wire`) -> `HandHistoryEntry` --
 * same field-name/casing translation `mapMeldDict` above does for one meld, plus the
 * `winner_melds` -> `winnerMelds` array itself going through that same per-meld mapper. */
function mapHandHistoryEntry(h: HandHistoryEntryPayload): HandHistoryEntry {
	return {
		handNo: h.hand_no,
		outcome: h.outcome,
		winner: h.winner,
		winType: h.win_type,
		discarder: h.discarder,
		faan: h.faan,
		faanBreakdown: h.faan_breakdown,
		points: h.points,
		payments: h.payments,
		revealed: h.revealed,
		winningHand: h.winning_hand,
		dealer: h.dealer,
		prevailing: h.prevailing,
		winnerMelds: h.winner_melds ? h.winner_melds.map(mapMeldDict) : null
	};
}

/** `state_sync.hand_history` (docs/02-protocol.md §3) exists precisely so a client with no
 * live memory of earlier hands -- a spectator joining mid-game, a reconnect-with-gap, a
 * backpressure-collapse resync -- can still show the full scoresheet. Merges it into whatever
 * `handHistory` this session already accumulated live rather than replacing it outright:
 * already-recorded hands (by `handNo`) keep their locally-captured entry (identical content in
 * practice, since the server redacts `winner_melds` for this same seat the same way), so this
 * never discards anything a live `hand_end` already built. Missing on older test fixtures
 * (`HandHistoryEntryPayload[]` is optional on the wire, protocol.d.ts) -- `?? []` treats that
 * exactly like "no hands to add," not an error. */
function mergeHandHistory(
	existing: readonly HandHistoryEntry[],
	fromWire: readonly HandHistoryEntryPayload[] | undefined
): HandHistoryEntry[] {
	if (!fromWire || fromWire.length === 0) return existing.slice();
	const known = new Set(existing.map((h) => h.handNo));
	const merged = existing.concat(
		fromWire.filter((h) => !known.has(h.hand_no)).map(mapHandHistoryEntry)
	);
	return merged.sort((a, b) => a.handNo - b.handNo);
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
				// no dedicated wire field for "held apart" (state.ts's `drawnTileId` doc) -- same
				// last-tile-in-hand inference `deal`/`draw` rely on, since a resync mid-`AWAIT_ACTION`
				// after a real draw has no other signal to reconstruct it from.
				drawnTileId:
					d.turn === d.seat && d.legal_actions.some((a) => a.kind === 'discard')
						? (d.own_hand[d.own_hand.length - 1] ?? null)
						: null,
				concealedCounts: d.concealed_counts.slice(),
				hands: d.hands ? d.hands.map((hand) => hand.slice()) : null,
				melds: d.melds.map((seatMelds) => seatMelds.map(mapMeldDict)),
				discardPools: d.discard_pools.map((pool) => pool.slice()),
				flowers: d.flowers.map((fl) => fl.slice()),
				wallRemaining: d.wall_remaining,
				seatStatus: d.seat_status.slice(),
				names: d.names.slice(),
				hostSeat: d.host_seat,
				scores: d.scores.slice(),
				legalActions: d.legal_actions,
				deadlineTs: d.deadline_ts,
				claimOffer:
					d.claim_options.length > 0
						? { windowId: null, options: d.claim_options, deadlineTs: d.deadline_ts }
						: null,
				// `d.turn` is the discarder for the whole embedded-claim-window lifetime (same
				// invariant the live `discard`/`turn` events maintain, see state.ts's `lastDiscard`
				// doc) -- derive it from `discard_pools` since a resync carries no dedicated field.
				lastDiscard:
					d.claim_options.length > 0 && d.discard_pools[d.turn].length > 0
						? {
								seat: d.turn,
								tileId: d.discard_pools[d.turn][d.discard_pools[d.turn].length - 1]
							}
						: null,
				handHistory: mergeHandHistory(state.handHistory, d.hand_history)
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
				drawnTileId: null,
				concealedCounts: [0, 0, 0, 0],
				// an open-hands spectator gets a fresh state_sync right after this, not a `deal`
				hands: state.hands === null ? null : [[], [], [], []],
				melds: [[], [], [], []],
				discardPools: [[], [], [], []],
				flowers: [[], [], [], []],
				claimOffer: null,
				legalActions: [],
				deadlineTs: null,
				lastHandEnd: null,
				handEndDeadlineTs: null,
				lastDiscard: null
			};
		}

		case 'deal': {
			const d = event.d;
			return {
				...state,
				ownHand: d.your_hand.slice(),
				// the dealer alone is dealt 14 (server/mahjong_core/wall.py's `deal_hands`: "the
				// dealer draws one further tile at the end"), appended last -- that bonus tile is
				// this seat's held-apart tile for turn one, same as any other draw.
				drawnTileId: d.your_hand.length > 13 ? d.your_hand[d.your_hand.length - 1] : null,
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
				ownHand: isOwn && d.replacement != null ? [...state.ownHand, d.replacement] : state.ownHand,
				// a flower auto-replaces from the wall (not a decision point) -- if this seat already
				// held a tile apart (mid-turn, or the dealer's deal-time bonus tile), the replacement
				// takes over that role; if not (another seat's deal-time flowers), still nothing to
				// hold apart.
				drawnTileId:
					isOwn && d.replacement != null && state.drawnTileId !== null
						? d.replacement
						: state.drawnTileId,
				// every flower_replace is one wall draw of the flower itself
				// (mahjong_core/engine.py's `_draw_replacing_flowers`) -- mirrors the `draw`/
				// `kong_replace` decrement below, since state_sync/deal are the only wire events
				// that carry wall_remaining directly.
				wallRemaining: Math.max(0, state.wallRemaining - 1)
			};
		}

		case 'draw': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			const tileId = d.tile_id;
			return {
				...state,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					state.concealedCounts[d.seat] + 1
				),
				hands:
					tileId != null ? updateHand(state.hands, d.seat, (h) => [...h, tileId]) : state.hands,
				ownHand: isOwn && d.tile_id != null ? [...state.ownHand, d.tile_id] : state.ownHand,
				drawnTileId: isOwn && d.tile_id != null ? d.tile_id : state.drawnTileId,
				wallRemaining: Math.max(0, state.wallRemaining - 1)
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
				hands: updateHand(state.hands, d.seat, (h) => removeOne(h, d.tile_id)),
				drawnTileId: isOwn ? null : state.drawnTileId,
				// a discard claimed later in the same server-side reduce() is removed from the
				// discarder's pool server-side (docs/02-protocol.md §3); this client-side pool can
				// transiently show it until the next state_sync corrects it — not attempted here.
				discardPools: replaceAt(state.discardPools, d.seat, pool),
				lastDiscard: { seat: d.seat, tileId: d.tile_id },
				// this seat just spent its turn -- `legal_actions`/`deadline_ts` from the `turn`
				// event that granted it are now stale (every remaining entry still names a tile_id
				// genuinely still in `ownHand`, since only the discarded one is gone, so a UI
				// reading `legalActions` alone can't tell they're dead). Left unset, they'd keep
				// looking actionable until the next `turn`/`claim_offer` overwrites them -- a real
				// client would let you click a second "legal-looking" discard that the server then
				// silently drops (`_authorize` on an out-of-turn command, docs/02-protocol.md §1's
				// ack note), which reads as the UI being stuck. Only this seat's own turn ends here;
				// another seat's `discard` doesn't touch this seat's own (already-empty-if-not-
				// acting) `legalActions`.
				legalActions: isOwn ? [] : state.legalActions,
				deadlineTs: isOwn ? null : state.deadlineTs
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
						isOwn && addedTile !== undefined ? removeOne(state.ownHand, addedTile) : state.ownHand,
					hands:
						addedTile !== undefined
							? updateHand(state.hands, d.seat, (h) => removeOne(h, addedTile))
							: state.hands,
					// declaring a kong consumes the held-apart tile into the meld; `kong_replace`
					// supplies the next one.
					drawnTileId: isOwn ? null : state.drawnTileId
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
					ownHand: isOwn && d.tiles ? removeMany(state.ownHand, d.tiles) : state.ownHand,
					hands: updateHand(state.hands, d.seat, (h) => removeMany(h, d.tiles ?? [])),
					drawnTileId: isOwn ? null : state.drawnTileId
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
				ownHand: isOwn && d.tiles ? removeMany(state.ownHand, d.tiles) : state.ownHand,
				// the claimed discard was never in this seat's hand, so removeOne skips it
				hands: updateHand(state.hands, d.seat, (h) => removeMany(h, d.tiles ?? [])),
				// a claimed chow/pung/kong is formed straight from the discard plus concealed tiles --
				// this seat never drew for it, so there's nothing held apart (the bug this field
				// exists to prevent: without it, whatever tile happened to end up last in `ownHand`
				// after `removeMany` above got shown as if freshly drawn).
				drawnTileId: isOwn ? null : state.drawnTileId
			};
		}

		case 'kong_replace': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			const tileId = d.tile_id;
			return {
				...state,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					state.concealedCounts[d.seat] + 1
				),
				hands:
					tileId != null ? updateHand(state.hands, d.seat, (h) => [...h, tileId]) : state.hands,
				ownHand: isOwn && d.tile_id != null ? [...state.ownHand, d.tile_id] : state.ownHand,
				drawnTileId: isOwn && d.tile_id != null ? d.tile_id : state.drawnTileId,
				wallRemaining: Math.max(0, state.wallRemaining - 1)
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
			const entry: HandHistoryEntry = {
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
				winningHand: d.winning_hand,
				// dealer/prevailing aren't on hand_end's own payload (docs/02-protocol.md §3) --
				// state.dealer/prevailing are still this hand's values, since only hand_start (which
				// always precedes the matching hand_end) changes them.
				dealer: state.dealer,
				prevailing: state.prevailing,
				// snapshotted now, not read later off `state.melds` -- the next `hand_start` clears
				// that array (state.ts's `HandHistoryEntry.winnerMelds` doc), so this is the only
				// point where the winner's melds are still available to capture for history.
				winnerMelds: d.winner !== null ? state.melds[d.winner].slice() : null
			};
			// socket.ts already drops a replayed frame by seq before it reaches here (a frame with
			// seq <= lastSeq never dispatches); this is defense in depth against the same hand_no
			// landing twice for any other reason, not the primary guard.
			const alreadyRecorded = state.handHistory.some((h) => h.handNo === d.hand_no);
			return {
				...state,
				lastHandEnd: entry,
				handEndDeadlineTs: d.deadline_ts,
				handHistory: alreadyRecorded ? state.handHistory : [...state.handHistory, entry],
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
			return {
				...state,
				seatStatus: replaceAt(state.seatStatus, d.seat, d.status),
				// carried on every seat_state broadcast for that seat, not just its first
				// (docs/02-protocol.md §3) -- mirrors seatStatus's own live-update above.
				names: d.name !== undefined ? replaceAt(state.names, d.seat, d.name) : state.names
			};
		}

		case 'server_shutdown':
			return { ...state, shutdownDeadlineTs: event.d.deadline_ts };

		default:
			return assertNever(event);
	}
}
