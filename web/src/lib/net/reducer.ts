import type { HandHistoryEntryPayload, ServerEvent } from './protocol';
import { type ClientGameState, type HandHistoryEntry, type MeldState } from '../game/state';
import type { RuleSet } from './ruleset';

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

/** `state_sync.melds` keys the meld kind as `kind`; the live `meld` event keys it as
 * `meld_kind` — two different upstream serializers for the same concept. */
function mapMeldDict(m: Record<string, unknown>): MeldState {
	return {
		kind: (m.kind ?? m.meld_kind) as string,
		tiles: m.tiles as number[],
		fromSeat: (m.from_seat as number | null | undefined) ?? null
	};
}

/** `state_sync.hand_history[i]` -> `HandHistoryEntry`, `winner_melds` mapped through `mapMeldDict`. */
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
		winnerMelds: h.winner_melds ? h.winner_melds.map(mapMeldDict) : null,
		...(h.fairness && {
			fairness: { handSeed: h.fairness.hand_seed, nonce: h.fairness.nonce, commit: null }
		})
	};
}

/** Merges wire hand_history into what this session already accumulated live, by `handNo` --
 * never clobbers an already-recorded hand, just backfills what a resync/spectator-join missed. */
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

/** Pure reducer: server event -> next `ClientGameState`. Exhaustive switch — `assertNever`
 * fails the build if `protocol.d.ts` grows a member this doesn't handle. */
export function reduce(state: ClientGameState, event: ServerEvent): ClientGameState {
	switch (event.t) {
		case 'pong':
			return state;

		case 'error':
			console.error('[reducer] server error', event.d.code, event.d.message);
			return state;

		case 'ack':
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
				// no dedicated wire field for "held apart" -- inferred as the last tile, same as deal/draw.
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
				botLevels: d.bot_levels?.slice() ?? [null, null, null, null],
				hostSeat: d.host_seat,
				ruleset: (d.ruleset as RuleSet | undefined) ?? null,
				rulesetPreset: d.ruleset_preset ?? null,
				seedCommit: d.seed_commit ?? null,
				scores: d.scores.slice(),
				legalActions: d.legal_actions,
				deadlineTs: d.deadline_ts,
				claimOffer:
					d.claim_options.length > 0
						? { windowId: null, options: d.claim_options, deadlineTs: d.deadline_ts }
						: null,
				// `d.turn` names the discarder for the window's lifetime; derived from `discard_pools`
				// since a resync carries no dedicated field.
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
				seedCommit: d.seed_commit ?? null,
				ownHand: [],
				drawnTileId: null,
				concealedCounts: [0, 0, 0, 0],
				// an open-hands spectator gets a fresh state_sync right after this, not a `deal`.
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
				// dealer alone is dealt 14, the bonus tile appended last and held apart for turn one.
				drawnTileId: d.your_hand.length > 13 ? d.your_hand[d.your_hand.length - 1] : null,
				concealedCounts: countsFromWire(d.counts),
				flowers: d.flowers.map((fl) => fl.slice()),
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
				// a flower auto-replaces, not a decision point -- the replacement takes over the
				// held-apart role only if this seat already had one.
				drawnTileId:
					isOwn && d.replacement != null && state.drawnTileId !== null
						? d.replacement
						: state.drawnTileId,
				// every flower_replace is one wall draw of the flower itself, same as draw/kong_replace.
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
				// a discard claimed later is popped back off in the `meld` case above, mirroring
				// mahjong_core.engine's own removal -- not left for the next state_sync to correct.
				discardPools: replaceAt(state.discardPools, d.seat, pool),
				lastDiscard: { seat: d.seat, tileId: d.tile_id },
				// stale own legal_actions would let a second click send an out-of-turn discard.
				// any seat's discard ends its turn deadline (opponents' rings read it too).
				legalActions: isOwn ? [] : state.legalActions,
				deadlineTs: null
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
			// a resolution for a window already moved past is stale and changes nothing.
			if (state.claimOffer && state.claimOffer.windowId !== d.window_id) return state;
			return { ...state, claimOffer: null };
		}

		case 'meld': {
			const d = event.d;
			const isOwn = d.seat === state.seat;
			const newMeld: MeldState = {
				kind: d.meld_kind,
				tiles: d.tiles,
				fromSeat: d.from_seat ?? null
			};

			if (d.meld_kind === 'added_kong') {
				// upgrades the existing pung in place rather than appending a stale duplicate entry.
				const claimTiles = d.tiles;
				const seatMelds = state.melds[d.seat];
				const pungIdx = seatMelds.findIndex(
					(existing) =>
						existing.kind === 'pung' && existing.tiles.every((t) => claimTiles.includes(t))
				);
				const nextSeatMelds =
					pungIdx === -1 ? [...seatMelds, newMeld] : replaceAt(seatMelds, pungIdx, newMeld);
				const oldPungTiles = pungIdx === -1 ? [] : seatMelds[pungIdx].tiles;
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
					// a kong consumes the held-apart tile; `kong_replace` supplies the next one.
					drawnTileId: isOwn ? null : state.drawnTileId,
					lastDiscard: null
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
					ownHand: isOwn ? removeMany(state.ownHand, d.tiles) : state.ownHand,
					hands: updateHand(state.hands, d.seat, (h) => removeMany(h, d.tiles)),
					drawnTileId: isOwn ? null : state.drawnTileId,
					lastDiscard: null
				};
			}

			// chow/pung/exposed_kong: `from_seat` set means exactly one tile of `tiles` came from
			// that seat's discard, the rest from this seat's own concealed hand.
			const claimedCount = d.from_seat != null ? 1 : 0;
			const fromHandCount = d.tiles.length - claimedCount;
			return {
				...state,
				melds,
				concealedCounts: replaceAt(
					state.concealedCounts,
					d.seat,
					Math.max(0, state.concealedCounts[d.seat] - fromHandCount)
				),
				ownHand: isOwn ? removeMany(state.ownHand, d.tiles) : state.ownHand,
				hands: updateHand(state.hands, d.seat, (h) => removeMany(h, d.tiles)),
				// mahjong_core.engine pops the claimed tile off the discarder's pool immediately (always
				// the last entry) -- mirrored here so pool_index doesn't misalign before the next state_sync.
				discardPools:
					claimedCount > 0
						? replaceAt(
								state.discardPools,
								d.from_seat as number,
								state.discardPools[d.from_seat as number].slice(0, -1)
							)
						: state.discardPools,
				// a claimed meld is never a draw -- without this, the last tile left in `ownHand`
				// after removeMany would show as if freshly drawn.
				drawnTileId: isOwn ? null : state.drawnTileId,
				lastDiscard: null,
				// a meld ends whatever turn was running; the next `turn` re-arms it.
				deadlineTs: null
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
				// not on hand_end's own payload -- only hand_start changes these, and it always
				// precedes the matching hand_end.
				dealer: state.dealer,
				prevailing: state.prevailing,
				// snapshotted now -- the next hand_start clears state.melds, so this is the only
				// point the winner's melds are still available to capture.
				winnerMelds: d.winner !== null ? state.melds[d.winner].slice() : null,
				...(d.fairness && {
					fairness: {
						handSeed: d.fairness.hand_seed,
						nonce: d.fairness.nonce,
						commit: state.seedCommit
					}
				})
			};
			// defense in depth against the same hand_no landing twice (socket.ts already drops
			// replays by seq before this).
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
				// carried on every seat_state broadcast for that seat, not just its first.
				names: d.name !== undefined ? replaceAt(state.names, d.seat, d.name) : state.names
			};
		}

		case 'server_shutdown':
			return { ...state, shutdownDeadlineTs: event.d.deadline_ts };

		default:
			return assertNever(event);
	}
}
