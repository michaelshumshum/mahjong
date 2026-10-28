<script lang="ts">
	import { untrack } from 'svelte';
	import { MediaQuery } from 'svelte/reactivity';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import type {
		ClaimOption,
		HandRecord,
		RoundResult,
		Seat,
		SeatInfo,
		Standing,
		Totals
	} from '$lib/game/types';
	import type { DeclareOption, OwnHandTile } from '$lib/table/view-types';
	import { seatAtPosition } from '$lib/table/wind';
	import {
		findRawClaimOption,
		legalClaimOptions,
		legalDeclareOptions,
		legalDiscardIds
	} from '$lib/table/legal-actions';
	import { MOCK_SCENARIOS } from '$lib/table/mock-game-state';
	import { MELD_SEAL_GLYPH } from '$lib/table/meld-face';
	import { PREGAME_PREVIEWS, type PregamePreview } from '$lib/table/pregame-preview';
	import { tileIdToCode } from '$lib/table/tile-code';
	import { moveTile, reconcileHandOrder } from '$lib/table/hand-order';
	import { meldToView, viewFromClientState, wireWindToCode } from '$lib/table/live-view';
	import { MahjongSocket, defaultWsUrl } from '$lib/net/socket';
	import { GameStore } from '$lib/game/store.svelte';
	import type { ClientGameState, ConnectionStatus, HandHistoryEntry } from '$lib/game/state';
	import type { ServerEvent } from '$lib/net/protocol';
	import ClaimDialog from '$lib/ui/ClaimDialog.svelte';
	import ScoreSheet from '$lib/ui/ScoreSheet.svelte';
	import GameEndScreen from '$lib/ui/GameEndScreen.svelte';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';
	import CoachMarks, { type CoachTarget } from '$lib/ui/CoachMarks.svelte';
	import Settings from '$lib/ui/Settings.svelte';
	import type { AutoArm, ClientPrefs } from '$lib/ui/client-prefs';
	import { isMotionReduced } from '$lib/ui/motion';
	import { applyClientPrefs } from '$lib/ui/apply-client-prefs';
	import { vibrate } from '$lib/ui/haptics';
	import {
		clearSeatForTable,
		clearSecretForTable,
		loadAutoArm,
		loadClientPrefs,
		DEFAULT_AUTO_ARM,
		DEFAULT_CLIENT_PREFS,
		loadDisplayName,
		loadOnboarding,
		loadPracticeSetup,
		loadSeatForTable,
		loadSecretForTable,
		saveAutoArm,
		saveClientPrefs,
		saveDisplayName,
		saveOnboarding,
		saveSeatForTable,
		saveSecretForTable
	} from '$lib/ui/settings-storage';
	import ToastStack from '$lib/ui/ToastStack.svelte';
	import Announcer from '$lib/ui/Announcer.svelte';
	import {
		announceSnapshot,
		announcementsBetween,
		type AnnounceSnapshot
	} from '$lib/ui/announcements';
	import ConnectionBanner from '$lib/ui/ConnectionBanner.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import { createToast, removeToast, type ToastEntry, type ToastSeverity } from '$lib/ui/toasts';
	import { serverErrorToastMessage } from '$lib/net/server-error-messages';
	import { shareOrCopy } from '$lib/ui/share-invite';
	import { createTable } from '$lib/net/lobby';
	import { PRACTICE_DIFFICULTY_TO_TIER } from '$lib/net/practice-difficulty';
	import { scheduleAutoDismiss } from '$lib/ui/auto-close';
	import CenterHub from '$lib/table/CenterHub.svelte';
	import TableScene from '$lib/table/TableScene.svelte';
	import HandEndOverlay from './_components/HandEndOverlay.svelte';
	import DismissablePanel from '$lib/ui/DismissablePanel.svelte';
	import ModalDialog from '$lib/ui/ModalDialog.svelte';
	import TableToolbar from './_components/TableToolbar.svelte';
	import PretableScreen from './_components/PretableScreen.svelte';
	import LeaveGameDialog from './_components/LeaveGameDialog.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { PHONE_LANDSCAPE_QUERY } from '$lib/ui/breakpoints';

	// `?mock=<scenarioId>` renders a frozen MOCK_SCENARIOS fixture with no backend (screenshot
	// workflow); omitted, `[id]` opens a real MahjongSocket -> GameStore through the same view model.
	let isMock = $derived(page.url.searchParams.has('mock'));
	let tableId = $derived(page.params.id ?? '');

	// `?practice=1` marks a practice table (POST /tables `practice: true`, seats 1-3 already
	// bot-bound) for the header tag and coach marks; the socket url doesn't carry it.
	let isPractice = $derived(page.url.searchParams.has('practice'));
	// phone landscape: the hub moves into the header rail, freeing a felt row (frontend.md §3).
	const phoneLandscape = new MediaQuery(PHONE_LANDSCAPE_QUERY);

	// `?pregame=connecting|join|waiting` freezes on one live pre-game state with no real socket --
	// a MOCK_SCENARIOS fixture (always fully-seated) has no room for these, so it's a mode of its own.
	let pregamePreview = $derived.by((): PregamePreview | null => {
		const raw = page.url.searchParams.get('pregame');
		return (PREGAME_PREVIEWS as readonly string[]).includes(raw ?? '')
			? (raw as PregamePreview)
			: null;
	});
	// arbitrary seat for the 'waiting' preview -- wind comes from whichever dealer the
	// MOCK_SCENARIOS fallback happens to carry.
	const PREGAME_PREVIEW_SEAT = 1 as Seat;

	// the url is the only scenario picker (/demo links to each); any value other than a known
	// scenario id (including a bare `?mock` flag) falls back to the first scenario.
	let scenarioId = $derived.by(() => {
		const raw = page.url.searchParams.get('mock');
		return MOCK_SCENARIOS.some((s) => s.id === raw) ? raw! : MOCK_SCENARIOS[0].id;
	});
	let mockGameState = $derived(
		(MOCK_SCENARIOS.find((s) => s.id === scenarioId) ?? MOCK_SCENARIOS[0]).state
	);

	// --- live connection -------------------------------------------------------------------
	let liveStore = $state<GameStore | null>(null);
	// no backend "has this table started" field -- state_sync reflects a fully-dealt hand from
	// creation, so this flips permanently on a real post-start broadcast or a mid-game reconnect snapshot.
	let handEverStarted = $state(false);
	let readySent = $state(false);

	function hasStartActivity(s: ClientGameState): boolean {
		return (
			s.discardPools.some((pool) => pool.some((id) => id !== undefined)) ||
			s.melds.some((seatMelds) => seatMelds.length > 0) ||
			s.handNo > 1 ||
			s.scores.some((score) => score !== 0)
		);
	}

	// discrete events that only exist once the table has actually started.
	const HAND_LIFECYCLE_EVENTS = new Set<string>([
		'hand_start',
		'draw',
		'discard',
		'meld',
		'kong_replace',
		'turn',
		'claim_offer',
		'flower_replace',
		'hand_end',
		'score',
		'game_end'
	]);

	$effect(() => {
		if (isMock || pregamePreview !== null) return;
		// resume from localStorage so `hello{seat}` reclaims the seat instead of falling into
		// the seat-picker's `join`, which fails with `table_full` once all seats are bound.
		const persistedSeat = loadSeatForTable(tableId);
		const persistedSecret = loadSecretForTable(tableId);
		// no persisted seat yet -- connect as a spectator so the seat picker shows real occupancy
		// instead of four identical "Open" slots; `join` promotes off spectator status on pick.
		const spectateParam = persistedSeat === null ? '&spectate=true' : '';
		const socket = new MahjongSocket(
			`${defaultWsUrl()}?table=${encodeURIComponent(tableId)}${spectateParam}`
		);
		const store = new GameStore(socket);
		handEverStarted = false;
		readySent = false;
		autoArmSent = false;
		liveStore = store;
		const offEvent = socket.onEvent((event: ServerEvent) => {
			if (!handEverStarted && HAND_LIFECYCLE_EVENTS.has(event.t)) handEverStarted = true;
			if (event.t === 'ack' && event.d.ok === false) {
				pushToast(
					m.tablePage_actionFailedToast({
						error: event.d.error ?? m.tablePage_unknownErrorLabel()
					}),
					'warn'
				);
			}
			// persist join's one-time reconnect credential so a later reload can present it back
			// on `hello{seat, secret}` instead of losing the seat.
			if (event.t === 'ack' && event.d.reconnect_secret != null) {
				saveSecretForTable(tableId, event.d.reconnect_secret);
			}
			if (event.t === 'error') {
				pushToast(serverErrorToastMessage(event.d.code, event.d.message), 'error');
				// a stale/wrong secret can never reclaim the seat; drop it so the next connect
				// falls back to spectator/seat-picker instead of retrying it.
				if (event.d.code === 'bad_secret') {
					clearSeatForTable(tableId);
					clearSecretForTable(tableId);
				}
			}
			// the game is over -- the reconnect credential is no longer valid.
			if (event.t === 'game_end') {
				clearSeatForTable(tableId);
				clearSecretForTable(tableId);
			}
			// waiting-room arrivals only -- once started, seat_state churns on every
			// disconnect/autoplay/reconnect, which isn't "a new player" news.
			if (
				event.t === 'seat_state' &&
				!handEverStarted &&
				(event.d.status === 'connected' || event.d.status === 'bot') &&
				event.d.seat !== liveStore?.state.seat
			) {
				pushToast(
					m.pretableScreen_arrivalToast({
						name: event.d.name ?? m.pretableScreen_anonymousPlayer()
					})
				);
			}
		});
		socket.connect(
			persistedSeat !== null ? { seat: persistedSeat, secret: persistedSecret } : undefined
		);
		return () => {
			offEvent();
			store.destroy();
			socket.disconnect();
			liveStore = null;
		};
	});

	// persist the seat the moment the server confirms it, so a later reload can resume it.
	$effect(() => {
		const seat = liveStore?.state.seat;
		if (seat !== null && seat !== undefined) saveSeatForTable(tableId, seat);
	});

	// sitting down implies readiness -- no reason to delay `ready` behind a second button.
	$effect(() => {
		const store = liveStore;
		if (!store || store.state.seat === null || readySent) return;
		readySent = true;
		store.socket.ready();
	});

	// re-assert on (re)connect, not read-back: the server never reports current auto-arm state,
	// so this re-sends the client's last persisted intent once per fresh connection.
	$effect(() => {
		const store = liveStore;
		if (!store || store.state.seat === null || autoArmSent) return;
		autoArmSent = true;
		store.socket.auto({ no_calls: autoArm.noCalls, auto_pass_chow: autoArm.autoPassChow });
	});

	$effect(() => {
		const store = liveStore;
		if (!store || handEverStarted) return;
		if (hasStartActivity(store.state)) handEverStarted = true;
	});

	// no seat of our own and none left to take: watch from seat 0's side instead of showing a
	// picker with nothing to pick. `handNo > 0` = a real state_sync has landed.
	let spectating = $derived(
		!isMock &&
			pregamePreview === null &&
			liveStore !== null &&
			liveStore.state.seat === null &&
			liveStore.state.handNo > 0 &&
			liveStore.state.seatStatus.every((status) => status !== 'empty')
	);

	let live = $derived(
		!isMock && liveStore ? viewFromClientState(liveStore.state, spectating ? 0 : null) : null
	);
	// falls back to the mock fixture when there's no live view yet -- never actually rendered,
	// since `tableReady` gates the template; this just keeps `gameState` non-null so it needs no null-checks.
	let gameState = $derived(isMock ? mockGameState : (live?.view ?? mockGameState));
	let tableReady = $derived(
		isMock ||
			(pregamePreview === null &&
				liveStore !== null &&
				liveStore.state.seat !== null &&
				handEverStarted) ||
			spectating
	);

	// the mural shows on this route's pregame states (connecting, seat picker, waiting-for-players
	// -- `tableReady` false) but never on the actual game table, mock or live, spectator included.
	claimMuralVisible(() => !tableReady);

	// unifies the real `liveStore`-driven pre-game states with the static `?pregame=` preview so
	// the template branches on one pair of values, instead of forking into two parallel conditionals.
	let previewConnection: ConnectionStatus = $derived(
		pregamePreview === 'connecting' ? 'connecting' : pregamePreview !== null ? 'open' : 'idle'
	);
	let effectiveConnection = $derived(
		pregamePreview !== null ? previewConnection : liveStore?.connection
	);
	let effectiveSeat = $derived(
		pregamePreview === 'waiting'
			? PREGAME_PREVIEW_SEAT
			: pregamePreview !== null
				? null
				: (liveStore?.state.seat ?? null)
	);
	// holding a seat means leaving costs something (autoplay handover) -- that path gets a
	// confirmation; spectating and mock/pregame previews don't.
	let isPlayer = $derived(!isMock && effectiveSeat !== null);

	let showLeaveConfirm = $state(false);
	function handleLeaveClick(): void {
		if (isPlayer) {
			showLeaveConfirm = true;
		} else {
			goto('/');
		}
	}
	function confirmLeaveGame(): void {
		showLeaveConfirm = false;
		goto('/');
	}
	// host = whichever seat's `join` was this table's first -- gates "Start with bots" below.
	let isHost = $derived(
		liveStore !== null &&
			liveStore.state.hostSeat !== null &&
			liveStore.state.hostSeat === liveStore.state.seat
	);

	// the table's URL *is* the invite -- lives on both the join and waiting screens, since
	// waiting for the table to fill is exactly when you need to hand it to someone.
	let copiedInviteLink = $state(false);
	let copyInviteLinkFailed = $state(false);
	const COPIED_RESET_MS = 2000;
	let cancelCopiedReset: (() => void) | null = null;

	async function shareInvite(): Promise<void> {
		const outcome = await shareOrCopy({
			url: window.location.href,
			title: m.pretableScreen_inviteShareTitle({ code: tableId }),
			text: m.pretableScreen_inviteShareText()
		});
		copyInviteLinkFailed = outcome === 'failed';
		if (outcome !== 'copied') return;
		copiedInviteLink = true;
		cancelCopiedReset?.();
		cancelCopiedReset = scheduleAutoDismiss(COPIED_RESET_MS, () => (copiedInviteLink = false));
	}

	$effect(() => () => cancelCopiedReset?.());

	// CenterHub's min-faan chip: the mock fixtures carry no ruleset, so they fall back to the
	// server default; live reads the real per-table ruleset once state_sync has landed.
	let minFaan = $derived(
		isMock ? (gameState.minFaan ?? 3) : (liveStore?.state.ruleset?.min_faan ?? null)
	);

	// manual hand order (ClientPrefs.handOrder): local presentation only, reconciled against the
	// live hand on every change so held tiles keep their place and new ones join at the right.
	let manualOrder = $state<number[]>([]);
	let arrangedConcealedIds = $derived.by((): number[] => {
		const concealedIds = live?.ownHand.concealedIds ?? [];
		return clientPrefs.handOrder === 'manual'
			? reconcileHandOrder(manualOrder, concealedIds)
			: concealedIds;
	});
	$effect(() => {
		const next = clientPrefs.handOrder === 'manual' ? arrangedConcealedIds : [];
		untrack(() => {
			if (next.length !== manualOrder.length || next.some((id, i) => manualOrder[i] !== id))
				manualOrder = next;
		});
	});

	function reorderHand(tileId: number, toIndex: number): void {
		manualOrder = moveTile(arrangedConcealedIds, tileId, toIndex);
	}

	// keyed by tile_id when live, so a reorder (or the drawn tile joining the hand) animates the
	// same element; mock fixtures have no ids, so they key by position.
	let ownHandTiles = $derived.by((): OwnHandTile[] => {
		const seat0 = seatAtPosition(gameState.seats, gameState.you, 0);
		const drawnId = live?.ownHand.drawnId ?? null;
		const tiles: OwnHandTile[] = live
			? arrangedConcealedIds.map((id) => ({
					key: `t-${id}`,
					code: tileIdToCode(id),
					tileId: id,
					drawn: false
				}))
			: (seat0.concealedHand ?? []).map((code, i) => ({
					key: `c-${i}`,
					code,
					tileId: null,
					drawn: false
				}));
		if (seat0.drawn) {
			tiles.push({
				key: drawnId !== null ? `t-${drawnId}` : 'drawn',
				code: seat0.drawn,
				tileId: drawnId,
				drawn: true
			});
		}
		return tiles;
	});

	let discardableTileIds = $derived(
		!isMock && liveStore ? legalDiscardIds(liveStore.state.legalActions) : new Set<number>()
	);

	function discardTile(tileId: number | null): void {
		if (isMock || !liveStore || tileId === null) return;
		liveStore.socket.discard(tileId);
	}

	let declareOptions = $derived.by((): DeclareOption[] => {
		if (isMock || !liveStore) return [];
		const store = liveStore;
		return legalDeclareOptions(store.state.legalActions, {
			win: () => store.socket.declareWin(),
			concealedKong: (tiles) => store.socket.declareConcealedKong(tiles),
			addedKong: (tiles) => store.socket.declareAddedKong(tiles)
		});
	});

	let claimOptions: ClaimOption[] | null = $derived(legalClaimOptions(gameState.claimWindow));
	let lastClaimChoice: ClaimOption | null = $state(null);

	// P3.3 haptics: a short pulse on your turn starting or a claim offer landing -- mobile
	// feature-detection lives in haptics.ts; this just decides *when*, on the rising edge.
	let hapticsPrevTurn = false;
	$effect(() => {
		const yourTurn = !isMock && discardableTileIds.size > 0;
		if (yourTurn && !hapticsPrevTurn && clientPrefs.haptics) vibrate(30);
		hapticsPrevTurn = yourTurn;
	});

	let hapticsPrevClaimOffer = false;
	$effect(() => {
		const offering = !isMock && !!claimOptions && claimOptions.length > 0;
		if (offering && !hapticsPrevClaimOffer && clientPrefs.haptics) vibrate(30);
		hapticsPrevClaimOffer = offering;
	});

	// P4.3 live announcements: diffed off the same view model the table renders, so mock and
	// live share it; a scenario/hand change only re-baselines (announcementsBetween).
	let announcer: Announcer | undefined = $state();
	let announcePrev: AnnounceSnapshot | null = null;
	$effect(() => {
		const handKey = `${isMock ? scenarioId : 'live'}:${gameState.handNo}`;
		const yourTurn = !isMock && discardableTileIds.size > 0;
		const next = announceSnapshot(gameState, handKey, yourTurn, spectating);
		const lines = announcementsBetween(announcePrev, next, clientPrefs.announceAllDiscards);
		announcePrev = next;
		announcer?.announce(lines);
	});

	// P3.1(d) claim seal stamp: a transient signal off a seat's own meld count growing, never
	// set under reduced motion. Keyed on `scenarioId`/`handNo` so a scenario/hand change resets.
	let sealStamp = $state<{ seat: number; glyph: string; key: number } | null>(null);
	let sealPrevMeldCounts: number[] = [0, 0, 0, 0];
	let sealPrevHandKey: string | null = null;
	let sealStampSeq = 0;
	let sealStampTimer: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		const seats = gameState.seats;
		const handKey = `${isMock ? scenarioId : 'live'}:${gameState.handNo}`;
		if (sealPrevHandKey === handKey && !isMotionReduced()) {
			for (const s of seats) {
				const prevCount = sealPrevMeldCounts[s.seat] ?? 0;
				if (s.melds.length > prevCount) {
					const newest = s.melds[s.melds.length - 1];
					sealStampSeq += 1;
					const seq = sealStampSeq;
					if (sealStampTimer !== null) clearTimeout(sealStampTimer);
					sealStamp = { seat: s.seat, glyph: MELD_SEAL_GLYPH[newest.kind], key: seq };
					sealStampTimer = setTimeout(() => {
						if (sealStampSeq === seq) sealStamp = null;
					}, 900);
				}
			}
		}
		sealPrevMeldCounts = seats.map((s) => s.melds.length);
		sealPrevHandKey = handKey;
	});

	$effect(() => {
		return () => {
			if (sealStampTimer !== null) clearTimeout(sealStampTimer);
		};
	});

	// P3.1(e) score-delta chips: same transient-signal pattern, off `handResult.payments` once
	// per hand end, cleared after a few seconds -- just a glance near the plate.
	let scoreDeltaSignals = $state<Record<number, { value: number; key: number }>>({});
	let scoreDeltaPrevHandKey: string | null = null;
	let scoreDeltaSeq = 0;
	let scoreDeltaTimer: ReturnType<typeof setTimeout> | null = null;

	$effect(() => {
		const result = gameState.handResult;
		const handKey = `${isMock ? scenarioId : 'live'}:${gameState.handNo}`;
		if (scoreDeltaPrevHandKey === handKey) return;
		scoreDeltaPrevHandKey = handKey;
		if (!result || !result.payments || isMotionReduced()) return;
		scoreDeltaSeq += 1;
		const seq = scoreDeltaSeq;
		const next: Record<number, { value: number; key: number }> = {};
		for (const [seat, value] of Object.entries(result.payments)) {
			next[Number(seat)] = { value: value as number, key: seq };
		}
		scoreDeltaSignals = next;
		if (scoreDeltaTimer !== null) clearTimeout(scoreDeltaTimer);
		scoreDeltaTimer = setTimeout(() => {
			if (scoreDeltaSeq === seq) scoreDeltaSignals = {};
		}, 2400);
	});

	$effect(() => {
		return () => {
			if (scoreDeltaTimer !== null) clearTimeout(scoreDeltaTimer);
		};
	});

	// hand-end hold: dismissing is per-seat, tracked locally and sent once via `hand_end_ack` --
	// reset per hand, mirroring `readySent`'s one-shot pattern but keyed on `handNo`.
	let handEndAckSent = $state(false);
	$effect(() => {
		void gameState.handNo;
		handEndAckSent = false;
	});
	// mock mode and spectators have no hand_end_ack round trip to hide the overlay behind --
	// dismissing just closes it locally, reset when the `?mock=` scenario or the hand changes.
	let handEndDismissedLocally = $state(false);
	$effect(() => {
		void scenarioId;
		void gameState.handNo;
		handEndDismissedLocally = false;
	});

	function dismissHandEnd(): void {
		if (isMock || spectating) {
			handEndDismissedLocally = true;
			return;
		}
		if (handEndAckSent || !liveStore) return;
		handEndAckSent = true;
		liveStore.socket.handEndAck();
	}

	let liveRawClaimOptions = $derived(
		!isMock ? (liveStore?.state.claimOffer?.options ?? null) : null
	);

	function chooseClaim(option: ClaimOption): void {
		lastClaimChoice = option;
		if (isMock || !liveStore || !gameState.claimWindow) return;
		const raw = findRawClaimOption(liveRawClaimOptions, option);
		const tiles = raw?.tiles as number[] | undefined;
		liveStore.socket.claim(gameState.claimWindow.windowId, option.kind, tiles);
	}

	// minimal chrome to prove ScoreSheet/Settings/Toast compose into the scene -- not final
	// chrome, just reachability.
	let showScoreSheet = $state(false);
	let showSettings = $state(false);

	let scoreSeats: SeatInfo[] = $derived(
		gameState.seats.map((s) => ({ seat: s.seat as SeatInfo['seat'], name: s.name }))
	);
	let scoreTotals: Totals = $derived(
		Object.fromEntries(gameState.seats.map((s) => [s.seat, s.score])) as Totals
	);
	let seatNames: Record<0 | 1 | 2 | 3, string> = $derived(
		Object.fromEntries(gameState.seats.map((s) => [s.seat, s.name])) as Record<
			0 | 1 | 2 | 3,
			string
		>
	);
	// this hand's per-round detail: undefined for a mock's synthesized row when the frozen
	// scenario has no handResult, otherwise built off the same fields FaanBreakdown reads.
	function mockRoundResult(): RoundResult | undefined {
		const result = gameState.handResult;
		if (!result) return undefined;
		if (result.outcome !== 'win') return { outcome: 'exhaustive_draw' };
		return {
			outcome: 'win',
			winner: result.winner,
			winningHand: result.winningHand ?? [],
			melds: gameState.seats[result.winner!]?.melds ?? [],
			patterns: result.patterns ?? [],
			totalFaan: result.totalFaan ?? 0,
			payments: result.payments ?? {}
		};
	}

	// past-round detail off HandHistoryEntry: winnerMelds/winningHand are real tile_ids, converted
	// the same way live-view.ts's seat mapping does -- the one place a past round's hand is reconstructed.
	function liveRoundResult(h: HandHistoryEntry): RoundResult | undefined {
		if (h.outcome !== 'win' || h.winner === null) {
			return h.outcome === 'exhaustive_draw' ? { outcome: 'exhaustive_draw' } : undefined;
		}
		return {
			outcome: 'win',
			winner: h.winner as RoundResult['winner'],
			winningHand: h.winningHand ? h.winningHand.map(tileIdToCode) : [],
			melds: h.winnerMelds ? h.winnerMelds.map(meldToView) : [],
			patterns: h.faanBreakdown
				? Object.entries(h.faanBreakdown).map(([name, faan]) => ({ name, faan }))
				: [],
			totalFaan: h.faan ?? 0,
			payments: (h.payments ?? {}) as RoundResult['payments']
		};
	}

	// mock path: the one game-end scenario's fixed rounds, else a single row from the current snapshot.
	// live path: real accumulated `handHistory`, growing across a live multi-hand game.
	let scoreHands: HandRecord[] = $derived(
		isMock
			? (gameState.gameEnd?.rounds ?? [
					{
						handNo: gameState.handNo,
						dealer: gameState.dealer as HandRecord['dealer'],
						prevailing: gameState.prevailing,
						deltas: gameState.handResult?.payments ?? {},
						result: mockRoundResult()
					}
				])
			: (liveStore?.state.handHistory.map((h): HandRecord => ({
					handNo: h.handNo,
					dealer: h.dealer as HandRecord['dealer'],
					prevailing: wireWindToCode(h.prevailing),
					deltas: (h.payments ?? {}) as HandRecord['deltas'],
					result: liveRoundResult(h)
				})) ?? [])
	);

	// `game_end` only carries {hand_no, scores} -- absolute totals, no placement rules. Ranking
	// by raw total with a deterministic seat-order tiebreak; mock path reuses its own fixed standings.
	let scoreStandings: Standing[] | undefined = $derived(
		isMock
			? gameState.gameEnd?.standings
			: liveStore?.state.gameEnd
				? liveStore.state.gameEnd.scores
						.map((total, seat) => ({ seat: seat as Standing['seat'], total }))
						.sort((a, b) => b.total - a.total || a.seat - b.seat)
				: undefined
	);

	// `game_end` fires only after the last hand's hold resolves, but the hold overlay has no other
	// way to know that (it normally clears on the next `hand_start`, absent for the final hand) -- `!gameEndReached` closes it.
	let gameEndReached = $derived(
		isMock ? gameState.gameEnd != null : liveStore?.state.gameEnd != null
	);

	// practice "Play again": a fresh table with the last-used bot levels. A full navigation, not
	// goto() -- the reused route component would carry this table's local flags into the next.
	let playAgainPending = $state(false);
	let playAgainFailed = $state(false);

	async function playAgain(): Promise<void> {
		playAgainPending = true;
		playAgainFailed = false;
		const setup = loadPracticeSetup() ?? { 1: 'normal', 2: 'normal', 3: 'normal' };
		try {
			const { table_id } = await createTable({
				practice: true,
				bot_tiers: {
					1: PRACTICE_DIFFICULTY_TO_TIER[setup[1]],
					2: PRACTICE_DIFFICULTY_TO_TIER[setup[2]],
					3: PRACTICE_DIFFICULTY_TO_TIER[setup[3]]
				}
			});
			window.location.assign(`/table/${encodeURIComponent(table_id)}?practice=1`);
		} catch {
			playAgainFailed = true;
			playAgainPending = false;
		}
	}

	// the hand is over while a result overlay is up, so no seat should still read as acting --
	// mock fixtures and the live reducer both leave `turn` on the last actor.
	let resultOverlayUp = $derived(
		gameEndReached ? !!scoreStandings : !!gameState.handResult && !handEndDismissedLocally
	);
	let haloTurn = $derived(resultOverlayUp ? -1 : gameState.turn);

	// first-hand coach marks: practice only (no other humans waiting on you), once per browser.
	let onboarding = $state(loadOnboarding() ?? { coachMarksDone: false });
	let coachTarget = $state<CoachTarget>(null);
	let showCoachMarks = $derived(
		isPractice &&
			!spectating &&
			!onboarding.coachMarksDone &&
			gameState.handNo === 1 &&
			!claimOptions &&
			!resultOverlayUp
	);
	function finishCoachMarks(): void {
		onboarding = { coachMarksDone: true };
		saveOnboarding(onboarding);
		coachTarget = null;
	}

	let showGuide = $state(false);
	let guideFocus = $state<string | null>(null);
	function openGuide(pattern: string | null = null): void {
		guideFocus = pattern;
		showGuide = true;
	}

	// persisted to localStorage. `autoArm` is "last known intent," not verified truth -- re-sent
	// on each fresh connection instead of read back. Display name persists the same way but is sent once on `join`.
	let displayName = $state(loadDisplayName() ?? '');
	function updateDisplayName(value: string): void {
		displayName = value;
		saveDisplayName(value);
	}

	let autoArm: AutoArm = $state(loadAutoArm() ?? { ...DEFAULT_AUTO_ARM });
	let clientPrefs: ClientPrefs = $state(loadClientPrefs() ?? { ...DEFAULT_CLIENT_PREFS });
	// guards the one-shot re-send above per live connection instance, mirroring `readySent`.
	let autoArmSent = $state(false);

	let toastQueue: ToastEntry[] = $state([]);
	function pushToast(message: string, severity: ToastSeverity = 'info'): void {
		toastQueue = [...toastQueue, createToast(message, undefined, severity)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}

	// tab title: your-turn/claim beats the generic table label. Mock scenarios are frozen
	// snapshots, not live turn state, so they always show the generic table title.
	let pageTitle = $derived(
		!isMock && claimOptions && claimOptions.length > 0
			? m.tablePage_titleClaim()
			: !isMock && discardableTileIds.size > 0
				? m.tablePage_titleYourTurn()
				: m.tablePage_titleTable({ code: tableId })
	);
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

{#if tableReady}
	<h1 class="sr-only">{m.tablePage_heading()}</h1>

	{#snippet hub()}
		<CenterHub
			prevailing={gameState.prevailing}
			handNo={gameState.handNo}
			dealer={gameState.dealer as Seat}
			turn={haloTurn as Seat}
			you={gameState.you}
			wallCount={gameState.wallCount}
			{minFaan}
			turnDurationMs={gameState.turnDurationMs}
		/>
	{/snippet}

	<div class="table-page">
		<TableToolbar
			hub={phoneLandscape.current ? hub : undefined}
			{spectating}
			{tableId}
			{isPractice}
			connection={liveStore?.connection}
			onLeaveClick={handleLeaveClick}
			onToggleScoreSheet={() => (showScoreSheet = !showScoreSheet)}
			onToggleSettings={() => (showSettings = !showSettings)}
			onOpenGuide={() => openGuide()}
		/>

		<div class="table-wrap" data-coach={showCoachMarks ? coachTarget : undefined}>
			{#if !isMock}
				<ConnectionBanner connection={liveStore?.connection} />
			{/if}
			<TableScene
				view={gameState}
				{spectating}
				{isMock}
				turn={haloTurn}
				hub={phoneLandscape.current ? undefined : hub}
				{ownHandTiles}
				{discardableTileIds}
				{declareOptions}
				discardMode={clientPrefs.discardMode}
				onDiscard={discardTile}
				arrangeable={!isMock && clientPrefs.handOrder === 'manual'}
				onReorder={reorderHand}
				scoreDeltas={scoreDeltaSignals}
				{sealStamp}
			/>
			{#if showCoachMarks}
				<div class="coach-anchor">
					<CoachMarks
						discardMode={clientPrefs.discardMode}
						onStepChange={(target) => (coachTarget = target)}
						onDone={finishCoachMarks}
					/>
				</div>
			{/if}
		</div>

		{#if claimOptions}
			<ModalDialog testid="claim-overlay" label={m.claimDialog_ariaLabel()} placement="sheet">
				<ClaimDialog
					discardTile={gameState.claimWindow?.tile ?? null}
					discarderName={gameState.claimWindow
						? gameState.seats[gameState.claimWindow.sourceSeat].name
						: null}
					options={claimOptions}
					durationMs={gameState.claimWindow?.durationMs ?? 0}
					onChoose={chooseClaim}
				/>
				{#if lastClaimChoice}
					<p class="sr-only" data-testid="claim-choice">
						{m.tablePage_claimChoiceLabel({ kind: lastClaimChoice.kind })}
					</p>
				{/if}
			</ModalDialog>
		{/if}

		{#if gameState.handResult && !gameEndReached && !handEndDismissedLocally}
			<HandEndOverlay
				handResult={gameState.handResult}
				handNo={gameState.handNo}
				handEndHoldMs={gameState.handEndHoldMs}
				{seatNames}
				winnerMelds={gameState.seats[gameState.handResult.winner as 0 | 1 | 2 | 3].melds}
				onDismiss={dismissHandEnd}
				onPatternSelect={openGuide}
			/>
		{/if}

		{#if gameEndReached && scoreStandings}
			<ModalDialog testid="game-end-overlay" labelledby="game-end-heading" placement="scroll">
				<div class="panel panel--scrollable">
					<GameEndScreen
						seats={scoreSeats}
						totals={scoreTotals}
						hands={scoreHands}
						standings={scoreStandings}
						you={spectating ? null : (gameState.you as Seat)}
						onPlayAgain={isPractice ? playAgain : undefined}
						{playAgainPending}
						{playAgainFailed}
					/>
				</div>
			</ModalDialog>
		{/if}

		{#if showScoreSheet}
			<DismissablePanel
				onClose={() => (showScoreSheet = false)}
				label={m.tableToolbar_scoreSheetButton()}
			>
				<ScoreSheet
					seats={scoreSeats}
					totals={scoreTotals}
					hands={scoreHands}
					standings={scoreStandings}
					onPatternSelect={openGuide}
				/>
			</DismissablePanel>
		{/if}

		{#if showSettings}
			<DismissablePanel onClose={() => (showSettings = false)} label={m.settings_title()}>
				<Settings
					{autoArm}
					prefs={clientPrefs}
					onAutoArmChange={(next) => {
						autoArm = next;
						saveAutoArm(next);
						if (!isMock)
							liveStore?.socket.auto({
								no_calls: next.noCalls,
								auto_pass_chow: next.autoPassChow
							});
					}}
					onPrefsChange={(next) => {
						clientPrefs = next;
						saveClientPrefs(next);
						applyClientPrefs(next);
					}}
					onReset={() => pushToast(m.settings_resetDone())}
				/>
			</DismissablePanel>
		{/if}

		{#if showGuide}
			<GuideDialog
				onClose={() => (showGuide = false)}
				tableRules={isMock ? null : (liveStore?.state.ruleset ?? null)}
				tablePreset={liveStore?.state.rulesetPreset ?? null}
				focusPattern={guideFocus}
			/>
		{/if}

		<ToastStack queue={toastQueue} onDismiss={dismissToast} />
		<Announcer bind:this={announcer} />
	</div>
{:else}
	<h1 class="sr-only">{m.tablePage_heading()}</h1>
	<div class="pretable-page">
		<PretableScreen
			{tableId}
			onLeaveClick={handleLeaveClick}
			{copiedInviteLink}
			{copyInviteLinkFailed}
			onInvite={shareInvite}
			{isPractice}
			{effectiveConnection}
			effectiveSeat={effectiveSeat as Seat | null}
			dealer={gameState.dealer as Seat}
			{displayName}
			onDisplayNameChange={updateDisplayName}
			seatStatus={liveStore?.state.seatStatus ?? []}
			names={liveStore?.state.names ?? []}
			onJoin={(seat) => liveStore?.socket.join(seat, displayName.trim() || undefined)}
			{isHost}
			onStartWithBots={() => liveStore?.socket.startWithBots()}
			rulesetPreset={liveStore?.state.rulesetPreset ?? null}
		/>
	</div>
	<ToastStack queue={toastQueue} onDismiss={dismissToast} />
{/if}

{#if showLeaveConfirm}
	<LeaveGameDialog onCancel={() => (showLeaveConfirm = false)} onConfirm={confirmLeaveGame} />
{/if}

<style lang="scss">
	@use '$lib/styles/layout';

	.table-page {
		display: flex;
		flex-direction: column;
		height: 100dvh;
		padding: var(--space-3);
		overflow: hidden;
	}

	// same centered-panel chrome as the lobby's own .panel, not a new visual language.
	.pretable-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100dvh;
		padding: var(--space-5);
	}

	.table-wrap {
		position: relative;
		flex: 1;
		min-height: 0;
	}

	// above the felt, below every overlay: a tip never covers a claim or result dialog.
	.coach-anchor {
		position: absolute;
		top: var(--space-3);
		left: 50%;
		z-index: var(--z-hud);
		transform: translateX(-50%);
	}

	.table-wrap[data-coach='hand'] :global(.seat-region--self),
	.table-wrap[data-coach='discards'] :global(.table-center) {
		outline: 2px solid var(--color-brass);
		outline-offset: 4px;
		border-radius: var(--radius-md);
	}

	// phone: .table-center has no box, so the tip outlines each pool instead.
	@include layout.phone-only {
		.table-wrap[data-coach='discards'] :global(.discard-pool) {
			outline: 2px solid var(--color-brass);
			outline-offset: 2px;
		}
	}

	// game-end content can be tall (podium + full score sheet + standings): the dialog scrolls
	// (placement="scroll") rather than clipping inside a fixed-height panel.
	.panel--scrollable {
		position: relative;
		width: 100%;
		margin-block: auto;
	}

	// sub-768px: the page scrolls instead of clipping; the surface fills at least the rest of the
	// viewport so the self row (sticky, last grid row) starts at the bottom.
	@include layout.phone-only {
		.table-page {
			height: auto;
			min-height: 100dvh;
			overflow: visible;
		}

		.table-wrap {
			display: flex;
			flex-direction: column;
		}
	}

	@include layout.desktop-up {
		.table-page {
			padding: var(--space-4) var(--space-5);
		}
	}

	// a phone held sideways: no page scroll -- the surface (TableScene) takes what the toolbar
	// leaves and scrolls inside itself.
	@include layout.phone-landscape {
		.table-page {
			height: 100dvh;
			min-height: 0;
			overflow: hidden;
			padding: 0 var(--space-2) var(--space-1);
		}

		.table-wrap {
			flex: 1;
			min-height: 0;
		}
	}

	// portrait phone: page padding, rim and felt padding (TableScene) cost ~22% of a 390px width;
	// the hand gets it back (two rows of ~46px tiles instead of ~40px).
	@include layout.phone-portrait {
		.table-page {
			padding: var(--space-1);
		}
	}
</style>
