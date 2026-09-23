<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import TileFace from '$lib/table/TileFace.svelte';
	import {
		MOCK_SCENARIOS,
		relativeSeat,
		type MockSeatState,
		type Seat
	} from '$lib/table/mock-game-state';
	import { tileIdToCode } from '$lib/table/tile-code';
	import { meldToView, viewFromClientState, wireWindToCode } from '$lib/table/live-view';
	import { MahjongSocket, defaultWsUrl } from '$lib/net/socket';
	import { GameStore } from '$lib/game/store.svelte';
	import type { ClientGameState, ConnectionStatus, HandHistoryEntry } from '$lib/game/state';
	import type { ServerEvent } from '$lib/net/protocol';
	import ClaimDialog from '$lib/ui/ClaimDialog.svelte';
	import type { ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import ScoreSheet, {
		type HandRecord,
		type RoundResult,
		type SeatInfo,
		type Standing,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';
	import GameEndScreen from '$lib/ui/GameEndScreen.svelte';
	import Settings, { type AutoArm, type ClientPrefs } from '$lib/ui/Settings.svelte';
	import {
		loadAutoArm,
		loadClientPrefs,
		loadDisplayName,
		loadSeatForTable,
		loadSecretForTable,
		saveAutoArm,
		saveClientPrefs,
		saveDisplayName,
		saveSeatForTable,
		saveSecretForTable
	} from '$lib/ui/settings-storage';
	import ToastStack from '$lib/ui/ToastStack.svelte';
	import AnimationDemoPanel from './_components/AnimationDemoPanel.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';
	import type { TileCode } from '$lib/table/tile-code';
	import { WIND_LABEL, WIND_CHAR, seatWind } from '$lib/table/wind';
	import SeatRing from '$lib/table/SeatRing.svelte';
	import SeatPicker from '$lib/table/SeatPicker.svelte';
	import OpponentRegion from '$lib/table/OpponentRegion.svelte';
	import CenterDiscardPool from '$lib/table/CenterDiscardPool.svelte';
	import YourSeatRegion from '$lib/table/YourSeatRegion.svelte';
	import HandEndOverlay from './_components/HandEndOverlay.svelte';
	import DismissablePanel from '$lib/ui/DismissablePanel.svelte';
	import DevToolbar from './_components/DevToolbar.svelte';

	// --- mock vs. live (docs/03-frontend.md §6's WS/reducer/store plumbing, wired into this
	// route) -----------------------------------------------------------------------------------
	// `?mock=<scenarioId>` (any value, or bare `?mock`) renders a frozen MOCK_SCENARIOS fixture
	// -- the screenshot workflow (.claude/skills/frontend-screenshots/SKILL.md) and design
	// iteration need this to keep working with no backend running. Omitted, `[id]` is treated as
	// a real table id and this opens a real MahjongSocket -> GameStore against it. Both paths
	// render through the same MockGameState-shaped view model (`gameState` below) so the
	// template/component tree never forks (`$lib/table/live-view.ts`'s module doc).
	let isMock = $derived(page.url.searchParams.has('mock'));
	let tableId = $derived(page.params.id ?? '');

	// `?practice=1` (this route's own query param, set by the lobby's "Play vs bots" button --
	// spelling is unrelated to the wire's own `&practice=true`) opens the live socket in M4.5
	// practice mode: seats 1-3 are bot-bound at table *creation* (server/app/ws.py's
	// `ws_endpoint`/`app/table.py`'s `Table.__init__(practice=...)`), so the human's own `join`
	// (still a real intent, same seat-picker flow below) is the only one this page ever sends.
	let isPractice = $derived(page.url.searchParams.has('practice'));

	// `?pregame=connecting|join|waiting` freezes on one live pre-game state with no real socket
	// -- these states depend on `liveStore.connection`/`.state.seat` transitions that a static
	// `MOCK_SCENARIOS` fixture (which always renders a fully-seated, already-dealt table, see
	// `tableReady` below) has no room for, so they need a mode of their own rather than folding
	// into `?mock`. Same "no backend running" posture as `?mock`, for the screenshot workflow
	// (.claude/skills/frontend-screenshots/SKILL.md) and design iteration.
	const PREGAME_PREVIEWS = ['connecting', 'join', 'waiting'] as const;
	type PregamePreview = (typeof PREGAME_PREVIEWS)[number];
	let pregamePreview = $derived.by((): PregamePreview | null => {
		const raw = page.url.searchParams.get('pregame');
		return (PREGAME_PREVIEWS as readonly string[]).includes(raw ?? '')
			? (raw as PregamePreview)
			: null;
	});
	// arbitrary seat for the 'waiting' preview -- its wind comes from whichever dealer the
	// MOCK_SCENARIOS fallback below happens to carry, same as any other pre-join reuse of
	// `gameState`/`seatWind` here.
	const PREGAME_PREVIEW_SEAT = 1 as Seat;

	// `?mock=<scenarioId>` jumps straight to that scenario; any other value (including the bare
	// `?mock` flag used just to select the mock path at all) falls back to the first one.
	let initialMockParam = page.url.searchParams.get('mock');
	let scenarioId = $state(
		MOCK_SCENARIOS.some((s) => s.id === initialMockParam) ? initialMockParam! : MOCK_SCENARIOS[0].id
	);
	let mockGameState = $derived(
		(MOCK_SCENARIOS.find((s) => s.id === scenarioId) ?? MOCK_SCENARIOS[0]).state
	);

	// --- live connection -------------------------------------------------------------------
	let liveStore = $state<GameStore | null>(null);
	// there's no backend "has this table actually started" field (state_sync's own snapshot
	// already reflects a fully-dealt hand the instant the table is created -- mahjong_core's
	// `new_game()` deals immediately, before any `ready` -- so `phase`/`own_hand` can't
	// distinguish "waiting for the table to fill" from "already playing"). Tracked here
	// instead: flips permanently once a genuine post-start broadcast is observed, or the very
	// first snapshot already shows unambiguous play-in-progress evidence (reconnect mid-game).
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

	// discrete events that only exist once `Table.started` (app/table.py) -- unlike a state_sync
	// snapshot, these can't have been computed ahead of the table actually dealing/turning.
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
		// a page reload builds a fresh MahjongSocket with no memory of which seat this browser
		// held -- resume it from localStorage so `hello{seat}` reclaims the seat (docs/02
		// -protocol.md §5) instead of falling into the seat-picker's `join`, which fails
		// with `table_full` once all four seats are already bound to this game's players.
		const persistedSeat = loadSeatForTable(tableId);
		const persistedSecret = loadSecretForTable(tableId);
		const practiceParam = isPractice ? '&practice=true' : '';
		// no persisted seat yet -- connect as a spectator first so the seat picker below can
		// show real occupancy (`state_status`/`names`) instead of four identical "Open" slots.
		// `join` promotes this connection off spectator status the moment a seat is chosen
		// (docs/00-architecture.md §3's "Spectating" note), so this never blocks becoming a
		// real seat.
		const spectateParam = persistedSeat === null ? '&spectate=true' : '';
		const socket = new MahjongSocket(
			`${defaultWsUrl()}?table=${encodeURIComponent(tableId)}${practiceParam}${spectateParam}`
		);
		const store = new GameStore(socket);
		handEverStarted = false;
		readySent = false;
		autoArmSent = false;
		liveStore = store;
		const offEvent = socket.onEvent((event: ServerEvent) => {
			if (!handEverStarted && HAND_LIFECYCLE_EVENTS.has(event.t)) handEverStarted = true;
			if (event.t === 'ack' && event.d.ok === false) {
				pushToast(`Action failed: ${event.d.error ?? 'unknown error'}`);
			}
			// join's own ack carries this seat's one-time reconnect credential
			// (00-architecture.md §2.1) -- persist it alongside the seat number so a later page
			// reload can present it back on `hello{seat, secret}` instead of losing the seat.
			if (event.t === 'ack' && event.d.reconnect_secret != null) {
				saveSecretForTable(tableId, event.d.reconnect_secret);
			}
			if (event.t === 'error') {
				pushToast(`Server error: ${event.d.message}`);
			}
			// Waiting-room arrivals only -- once the table has actually started, seat_state
			// churns on every disconnect/autoplay/reconnect, which isn't "a new player" news.
			if (
				event.t === 'seat_state' &&
				!handEverStarted &&
				(event.d.status === 'connected' || event.d.status === 'bot') &&
				event.d.seat !== liveStore?.state.seat
			) {
				pushToast(`${event.d.name ?? 'A player'} took a seat.`);
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

	// sitting down implies readiness -- no strategic reason to delay `ready` behind a second
	// button once the player has already made the one real decision (join this table).
	$effect(() => {
		const store = liveStore;
		if (!store || store.state.seat === null || readySent) return;
		readySent = true;
		store.socket.ready();
	});

	// Re-assert on (re)connect, not read-back: the server never reports a seat's current
	// auto-arm state, so this re-sends the client's last persisted intent once per fresh
	// connection that successfully seats us, rather than assuming the server already agrees.
	// Mock mode has no real socket (`liveStore` stays null there), so this is a no-op under
	// `?mock=`.
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

	// no seat of our own and none left to take (docs/03-frontend.md's "Spectating"): watch from
	// seat 0's side instead of showing a picker with nothing to pick. `handNo > 0` = a real
	// `state_sync` has landed; before that `seatStatus` is just the initial placeholder.
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
	// falls back to the mock fixture when there's no live view yet (pre-join/pre-start) --
	// never actually rendered in that case, since `tableReady` below gates the whole template;
	// this just keeps `gameState` non-null so the rest of the (unchanged) template below doesn't
	// need null-checks sprinkled through it.
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

	// unifies the real `liveStore`-driven pre-game states with the static `?pregame=` preview
	// (above) so the template below branches on one pair of values regardless of which is
	// driving them, instead of forking into two parallel conditionals.
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
	// holding a seat (incl. the pre-start waiting room) means leaving costs something -- an
	// autoplay handover, a seat someone else might take -- so that path gets a confirmation;
	// spectating (this connection has no seat, above) and mock/pregame previews don't.
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
	// host = whichever seat's `join` was this table's first (docs/02-protocol.md §2's "Host
	// definition") -- gates the "Start with bots" shortcut below. `?pregame=` previews have no
	// real `hostSeat` to compare against, so they never show it.
	let isHost = $derived(
		liveStore !== null &&
			liveStore.state.hostSeat !== null &&
			liveStore.state.hostSeat === liveStore.state.seat
	);

	// --- pre-game invite link (live mode only) ----------------------------------------------
	// the table's URL *is* the invite -- whoever opens it lands in this same table (docs/03
	// -frontend.md's "/table/[id] wiring": [id] is a real table id, auto-created on first
	// connect). Waiting for the table to fill is exactly the moment you need to hand that link
	// to someone, so it lives on both the join and waiting screens, not tucked in the lobby.
	let copiedInviteLink = $state(false);
	let copyInviteLinkFailed = $state(false);

	async function copyInviteLink(): Promise<void> {
		try {
			await navigator.clipboard.writeText(window.location.href);
			copiedInviteLink = true;
			copyInviteLinkFailed = false;
		} catch {
			copiedInviteLink = false;
			copyInviteLinkFailed = true;
		}
	}

	function seatAt(position: 0 | 1 | 2 | 3): MockSeatState {
		return gameState.seats.find((s) => relativeSeat(s.seat, gameState.you) === position)!;
	}

	// --- your hand: real discard/declare interactivity (live only) -------------------------
	interface OwnHandTile {
		key: string;
		code: TileCode;
		tileId: number | null;
		drawn: boolean;
	}

	let ownHandTiles = $derived.by((): OwnHandTile[] => {
		const seat0 = seatAt(0);
		const concealedIds = live?.ownHand.concealedIds ?? [];
		const drawnId = live?.ownHand.drawnId ?? null;
		const tiles: OwnHandTile[] = (seat0.concealedHand ?? []).map((code, i) => ({
			key: `c-${i}`,
			code,
			tileId: concealedIds[i] ?? null,
			drawn: false
		}));
		if (seat0.drawn) {
			tiles.push({ key: 'drawn', code: seat0.drawn, tileId: drawnId, drawn: true });
		}
		return tiles;
	});

	let discardableTileIds = $derived(
		new Set(
			!isMock && liveStore
				? liveStore.state.legalActions
						.filter((a) => a.kind === 'discard')
						.map((a) => a.tile_id as number)
				: []
		)
	);

	function discardTile(tileId: number | null): void {
		if (isMock || !liveStore || tileId === null) return;
		liveStore.socket.discard(tileId);
	}

	interface DeclareOption {
		key: string;
		label: string;
		onClick: () => void;
	}

	// legal_actions' own kind tags (mahjong_core.actions.action_to_dict) are the longer
	// `declare_*`/`claim_*` forms; the wire `declare{kind}` intent takes the shorter
	// `concealed_kong|added_kong|win` (docs/02-protocol.md §2's DeclarePayload) -- two different
	// vocabularies for the same concept, same shape of mismatch reducer.ts's `mapMeldDict`
	// comment already flags for melds.
	let declareOptions = $derived.by((): DeclareOption[] => {
		if (isMock || !liveStore) return [];
		const options: DeclareOption[] = [];
		for (const action of liveStore.state.legalActions) {
			const meld = action.meld as { tiles?: number[] } | undefined;
			if (action.kind === 'declare_win') {
				const store = liveStore;
				options.push({ key: 'win', label: 'Win', onClick: () => store.socket.declareWin() });
			} else if (action.kind === 'declare_concealed_kong' && meld?.tiles) {
				const store = liveStore;
				const tiles = meld.tiles;
				options.push({
					key: `ck-${tiles.join(',')}`,
					label: `Concealed kong ${tiles.map(tileIdToCode).join('-')}`,
					onClick: () => store.socket.declareConcealedKong(tiles)
				});
			} else if (action.kind === 'declare_added_kong' && meld?.tiles) {
				const store = liveStore;
				const tiles = meld.tiles;
				options.push({
					key: `ak-${tiles.join(',')}`,
					label: `Added kong ${tiles.map(tileIdToCode).join('-')}`,
					onClick: () => store.socket.declareAddedKong(tiles)
				});
			}
		}
		return options;
	});

	let claimOptions: ClaimOption[] | null = $derived(
		gameState.claimWindow?.yourOptions
			? gameState.claimWindow.yourOptions.map((o) => ({ kind: o.kind, tiles: o.tiles }))
			: null
	);
	let lastClaimChoice: ClaimOption | null = $state(null);

	// hand-end hold (docs/00-architecture.md §3): dismissing is per-seat, tracked locally and
	// (live mode) sent once via `hand_end_ack` -- reset per hand, mirroring `readySent`'s
	// one-shot-per-connection pattern above, but keyed on `handNo` instead of the socket effect.
	let handEndAckSent = $state(false);
	$effect(() => {
		void gameState.handNo;
		handEndAckSent = false;
	});
	// mock mode and spectators have no hand_end_ack round trip to hide the overlay behind (a
	// spectator isn't a seat the hold waits on) -- dismissing just closes it locally, reset
	// whenever the scenario picker jumps to a fresh one or the next hand starts.
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

	// the view model's `yourOptions` are display-only (TileCode, no id) -- recover the raw,
	// real-tile_id option `live-view.ts` built them from to submit the actual `claim` intent.
	let liveRawClaimOptions = $derived(
		!isMock ? (liveStore?.state.claimOffer?.options ?? null) : null
	);

	function findRawClaimOption(option: ClaimOption): Record<string, unknown> | undefined {
		const raw = liveRawClaimOptions;
		if (!raw) return undefined;
		const candidates = raw.filter((o) => o.kind === option.kind);
		if (candidates.length <= 1) return candidates[0];
		// only a chow claim can have more than one candidate for the same discard -- disambiguate
		// by which tile codes the option actually names (docs/02-protocol.md §2's `tiles`).
		const wanted = new Set(option.tiles ?? []);
		return candidates.find((o) => {
			const ids = (o.tiles as number[] | undefined) ?? [];
			const codes = new Set(ids.map(tileIdToCode));
			return codes.size === wanted.size && [...codes].every((c) => wanted.has(c));
		});
	}

	function chooseClaim(option: ClaimOption): void {
		lastClaimChoice = option;
		if (isMock || !liveStore || !gameState.claimWindow) return;
		const raw = findRawClaimOption(option);
		const tiles = raw?.tiles as number[] | undefined;
		liveStore.socket.claim(gameState.claimWindow.windowId, option.kind, tiles);
	}

	// minimal chrome to prove ScoreSheet/Settings/Toast compose into the scene without
	// layout collision (this sub-task's scope) — not the final chrome, just reachability.
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
	// this hand's per-round detail (ScoreSheet's expandable-row capability): `null` for a mock's
	// single synthesized row when the frozen scenario has no `handResult` (mid-game scenarios),
	// otherwise built straight off the same fields the live FaanBreakdown overlay above reads.
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

	// past-round detail off `HandHistoryEntry` (lib/game/state.ts): `winnerMelds`/`winningHand`
	// are real tile_ids, converted here the same way `live-view.ts`'s own seat mapping does
	// (`meldToView`/`tileIdToCode`) — this is the one place a *past* round's full winning hand
	// (melds included, not just the concealed tiles) is reconstructed, since `state.melds` itself
	// has long since reset by the time a player looks at game-end history (state.ts's
	// `winnerMelds` doc).
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

	// Mock path: either a fixed multi-hand `gameEnd` fixture (the one scenario that's actually
	// reached game end, `mock-game-state.ts`), or -- every other scenario -- one frozen,
	// already-dealt hand with no real `hand_end` stream behind it, so a single row synthesized
	// from the current snapshot is the correct (and only possible) rendering.
	// Live path: real accumulated history off `handHistory` (lib/game/state.ts), built by
	// lib/net/reducer.ts from every `hand_end` this session has actually seen — growing across a
	// live multi-hand game rather than showing just the latest hand.
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

	// `game_end` (docs/02-protocol.md §3) is a terminal, fires-once event carrying only
	// `{hand_no, scores}` — absolute final totals, no placement rules. Ranking by raw total is
	// the "straightforward" case ScoreSheet.svelte's `standings` doc comment calls out; anything
	// beyond that (tiebreak rules, etc.) isn't specified on the wire, so this doesn't invent one
	// beyond a deterministic seat-order tiebreak. Mock path reuses the one `gameEnd` scenario's
	// own fixed standings instead (there's no real `game_end` event behind it to derive from).
	let scoreStandings: Standing[] | undefined = $derived(
		isMock
			? gameState.gameEnd?.standings
			: liveStore?.state.gameEnd
				? liveStore.state.gameEnd.scores
						.map((total, seat) => ({ seat: seat as Standing['seat'], total }))
						.sort((a, b) => b.total - a.total || a.seat - b.seat)
				: undefined
	);

	// the actual game-end trigger (scope item 1): once real, this replaces the last hand's own
	// hold-and-ack overlay rather than following it. On the wire, `game_end` only ever fires
	// *after* that hold has already resolved (every seat acked, or the hold's own timeout) --
	// `app/table.py`'s `_apply`/`_advance_to_next_hand`, which is what actually calls
	// `start_next_hand()` (the only place `GameEnded` is produced) -- so there's no real "still
	// mid-hold" moment this ever preempts. But the client-side hold overlay has no other way to
	// know that hold is over: it normally clears on the *next* `hand_start` (reducer.ts), and for
	// the final hand there isn't one -- left alone, `gameState.handResult` would stay truthy
	// forever. Gating the hold overlay on `!gameEndReached` (below) is what actually closes it.
	let gameEndReached = $derived(
		isMock ? gameState.gameEnd != null : liveStore?.state.gameEnd != null
	);

	// Persisted to localStorage (lib/ui/settings-storage.ts) so a reload doesn't reset either
	// one back to these defaults. `autoArm` is "this client's last known intent," not verified
	// server truth -- there is no wire event that reports a seat's current `no_calls`/
	// `auto_pass_chow` back to the client (`seat_view_wire`/`state_sync` carry neither field,
	// docs/02-protocol.md §3), so the server is never read back here. Instead, the re-assert
	// effect below re-sends the persisted value once a fresh live connection seats us, so the
	// server's actual `SeatBinding` gets pulled back in line with it rather than silently
	// drifting after a reload creates a new `GameStore`/`MahjongSocket` with no memory of what
	// was last chosen. See docs/03-frontend.md §6 "Settings persistence".
	// Guest display name (docs/02-protocol.md's Auth section, M5): persisted the same way as
	// autoArm/clientPrefs above, but sent once as a plain field on `join`, not re-asserted on
	// every connection -- the server keeps it on the seat binding for the life of the game once
	// join carries it (a `hello` reconnect never resends it, see settings-storage.ts's own note).
	let displayName = $state(loadDisplayName() ?? '');
	function updateDisplayName(value: string): void {
		displayName = value;
		saveDisplayName(value);
	}

	let autoArm: AutoArm = $state(loadAutoArm() ?? { noCalls: false, autoPassChow: false });
	let clientPrefs: ClientPrefs = $state(
		loadClientPrefs() ?? { soundEnabled: true, motion: 'system' }
	);
	// Guards the one-shot re-send below per live connection instance, mirroring `readySent`.
	let autoArmSent = $state(false);

	let toastQueue: ToastEntry[] = $state([]);
	function pushToast(message: string): void {
		toastQueue = [...toastQueue, createToast(message)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}

	let showAnimationDemo = $state(false);
</script>

{#if tableReady}
	<h1 class="sr-only">Table</h1>

	<div class="table-page">
		<DevToolbar
			{isMock}
			bind:scenarioId
			{spectating}
			{tableId}
			{isPractice}
			seat={liveStore?.state.seat ?? null}
			wallCount={gameState.wallCount}
			prevailing={gameState.prevailing}
			onLeaveClick={handleLeaveClick}
			onToggleScoreSheet={() => (showScoreSheet = !showScoreSheet)}
			onToggleSettings={() => (showSettings = !showSettings)}
			onToast={() => pushToast('Reconnecting…')}
			onToggleAnimationDemo={() => (showAnimationDemo = !showAnimationDemo)}
		/>

		<div class="table-tilt">
			<div class="table-surface" data-testid="table-scene">
				<OpponentRegion
					seat={seatAt(2)}
					position="across"
					dealer={gameState.dealer as Seat}
					turn={gameState.turn}
				/>
				<OpponentRegion
					seat={seatAt(3)}
					position="left"
					dealer={gameState.dealer as Seat}
					turn={gameState.turn}
				/>
				<OpponentRegion
					seat={seatAt(1)}
					position="right"
					dealer={gameState.dealer as Seat}
					turn={gameState.turn}
				/>

				<div class="table-center">
					<CenterDiscardPool
						seat={seatAt(2)}
						position="across"
						ariaLabel="{seatAt(2).name}'s discards"
					/>
					<CenterDiscardPool
						seat={seatAt(3)}
						position="left"
						ariaLabel="{seatAt(3).name}'s discards"
					/>
					<CenterDiscardPool
						seat={seatAt(1)}
						position="right"
						ariaLabel="{seatAt(1).name}'s discards"
					/>
					<CenterDiscardPool
						seat={seatAt(0)}
						position="self"
						ariaLabel={spectating ? `${seatAt(0).name}'s discards` : 'Your discards'}
					/>
				</div>

				<YourSeatRegion
					seat={seatAt(0)}
					{spectating}
					dealer={gameState.dealer as Seat}
					turn={gameState.turn}
					turnDurationMs={gameState.turnDurationMs}
					{isMock}
					{ownHandTiles}
					{discardableTileIds}
					onDiscard={discardTile}
					{declareOptions}
				/>
			</div>
		</div>

		{#if claimOptions}
			<div class="claim-overlay" data-testid="claim-overlay">
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
					<p class="sr-only" data-testid="claim-choice">chose: {lastClaimChoice.kind}</p>
				{/if}
			</div>
		{/if}

		{#if gameState.handResult && !gameEndReached && !handEndDismissedLocally}
			<HandEndOverlay
				handResult={gameState.handResult}
				handNo={gameState.handNo}
				handEndHoldMs={gameState.handEndHoldMs}
				{seatNames}
				winnerMelds={gameState.seats[gameState.handResult.winner as 0 | 1 | 2 | 3].melds}
				onDismiss={dismissHandEnd}
			/>
		{/if}

		{#if gameEndReached && scoreStandings}
			<div class="panel-overlay" data-testid="game-end-overlay">
				<div class="panel">
					<GameEndScreen
						seats={scoreSeats}
						totals={scoreTotals}
						hands={scoreHands}
						standings={scoreStandings}
					/>
				</div>
			</div>
		{/if}

		{#if showScoreSheet}
			<DismissablePanel onClose={() => (showScoreSheet = false)}>
				<ScoreSheet
					seats={scoreSeats}
					totals={scoreTotals}
					hands={scoreHands}
					standings={scoreStandings}
				/>
			</DismissablePanel>
		{/if}

		{#if showSettings}
			<DismissablePanel onClose={() => (showSettings = false)}>
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
					}}
				/>
			</DismissablePanel>
		{/if}

		{#if showAnimationDemo}
			<AnimationDemoPanel onClose={() => (showAnimationDemo = false)} />
		{/if}

		<ToastStack queue={toastQueue} onDismiss={dismissToast} />
	</div>
{:else}
	<h1 class="sr-only">Table</h1>
	<div class="pretable-page">
		<div class="pretable-panel">
			<button type="button" class="pretable-leave" onclick={handleLeaveClick}>Leave game</button>
			<div class="pretable-info">
				<span>Table</span>
				<span class="pretable-code">{tableId}</span>
				<button type="button" class="pretable-link-btn" onclick={copyInviteLink}>
					{copiedInviteLink ? 'Copied' : 'Copy invite link'}
				</button>
			</div>
			{#if copyInviteLinkFailed}
				<p class="pretable-error">Couldn't copy automatically — copy the address bar instead.</p>
			{/if}

			{#if !effectiveConnection || effectiveConnection === 'idle' || effectiveConnection === 'connecting'}
				<div class="pretable-spinner"></div>
				<p class="pretable-status">Connecting…</p>
			{:else if effectiveSeat === null}
				<h2>Take a seat</h2>
				<p>Choose an open seat to sit down at this table.</p>
				<div class="pretable-name-field">
					<label class="pretable-name-label" for="display-name-input">Your name</label>
					<input
						id="display-name-input"
						type="text"
						class="pretable-name-input"
						maxlength="24"
						placeholder="Guest"
						autocomplete="off"
						value={displayName}
						oninput={(e) => updateDisplayName(e.currentTarget.value)}
					/>
				</div>
				<SeatPicker
					seatStatus={liveStore?.state.seatStatus ?? []}
					names={liveStore?.state.names ?? []}
					onJoin={(seat) => liveStore?.socket.join(seat, displayName.trim() || undefined)}
				/>
			{:else}
				<SeatRing
					you={effectiveSeat as Seat}
					dealer={gameState.dealer as Seat}
					seatStatus={liveStore?.state.seatStatus ?? []}
					names={liveStore?.state.names ?? []}
				/>
				<h2>You're seated as {WIND_LABEL[seatWind(effectiveSeat as Seat, gameState.dealer)]}</h2>
				<p>
					Waiting for the rest of the table to join. The hand starts automatically once all four
					seats are ready.
				</p>
				{#if isHost}
					<button
						type="button"
						class="pretable-cta"
						onclick={() => liveStore?.socket.startWithBots()}
					>
						Start with bots
					</button>
					<p class="pretable-hint">Fills every open seat with a bot and starts right away.</p>
				{/if}
			{/if}
		</div>
	</div>
	<ToastStack queue={toastQueue} onDismiss={dismissToast} />
{/if}

{#if showLeaveConfirm}
	<div class="panel-overlay">
		<div
			class="confirm-dialog"
			role="alertdialog"
			aria-label="Leave game"
			aria-describedby="leave-confirm-desc"
		>
			<h2>Leave this table?</h2>
			<p id="leave-confirm-desc">Your seat switches to autoplay until you reconnect.</p>
			<div class="confirm-actions">
				<button type="button" onclick={() => (showLeaveConfirm = false)}>Cancel</button>
				<button type="button" class="confirm-leave" onclick={confirmLeaveGame}>Leave game</button>
			</div>
		</div>
	</div>
{/if}

<style lang="scss">
	@use '$lib/styles/layout';
	@use '$lib/styles/buttons';

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		padding: 0;
		margin: -1px;
		overflow: hidden;
		clip: rect(0, 0, 0, 0);
		white-space: nowrap;
		border: 0;
	}

	.table-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		height: 100dvh;
		padding: var(--space-3);
		overflow: hidden;
	}

	// pre-game states (connecting / join / waiting-for-players, live mode only) -- same
	// centered-panel chrome as the lobby's own `.panel` (routes/+page.svelte), not a new
	// visual language: panel-elevated, --color-surface, the same button/code-pill vocabulary.
	.pretable-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100dvh;
		padding: var(--space-5);
	}

	.pretable-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		max-width: 26rem;
		padding: var(--space-6) var(--space-5);
		background: var(--color-surface);
		text-align: center;
		@include buttons.panel-elevated;

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}

		p {
			margin: 0;
			max-width: 40ch;
			color: var(--color-text-muted);
		}
	}

	.pretable-leave {
		align-self: flex-start;
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;
	}

	.pretable-info {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.pretable-code {
		font-family: monospace;
		font-size: var(--font-size-base);
		letter-spacing: 0.08em;
		color: var(--color-text);
		background: var(--color-surface-raised);
		border-radius: var(--radius-sm);
		padding: var(--space-1) var(--space-2);
	}

	.pretable-link-btn {
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;
	}

	.pretable-error {
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.pretable-status {
		font-size: var(--font-size-sm);
	}

	.pretable-cta {
		min-height: 44px;
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-primary;
	}

	.pretable-name-field {
		display: flex;
		flex-direction: column;
		align-items: flex-start;
		gap: var(--space-1);
		width: 100%;
		max-width: 16rem;
	}

	.pretable-name-label {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.pretable-name-input {
		width: 100%;
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		color: var(--color-text);
		@include buttons.input-recessed;

		&::placeholder {
			color: var(--color-text-muted);
		}
	}

	// indeterminate connection spinner -- no durationMs to anchor a TimerRing to (§5's
	// countdown mechanics are for a known deadline; this is "unknown, still trying").
	.pretable-spinner {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 3px solid var(--color-border);
		border-top-color: var(--color-accent);
		animation: pretable-spin 900ms linear infinite;
	}

	@keyframes pretable-spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.pretable-spinner {
			animation: none;
			opacity: 0.6;
		}
	}

	.pretable-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.table-tilt {
		flex: 1;
		min-height: 0;
		@include layout.table-perspective;
	}

	.table-surface {
		@include layout.seat-region-grid;
		height: 100%;
		min-height: 420px;
		padding: var(--space-3);
		// faint overhead-light falloff on the lacquered surface — a believable material cue,
		// not a texture asset; stays quiet enough that tiles (the brightest thing on screen,
		// §1) are unaffected.
		background:
			radial-gradient(ellipse 80% 60% at 50% 10%, rgb(255 255 255 / 0.035), transparent 65%),
			var(--color-surface);
		border-radius: var(--radius-md);
		transform: rotateX(6deg);
		transform-style: preserve-3d;

		@include layout.phone-only {
			transform: none; // tilt reads as decoration, not worth the layout cost on phone widths
			// `preserve-3d` alone (independent of `transform: none` above) still establishes a
			// containing block for `position: fixed` descendants -- `.seat-region--self` needs
			// the real viewport as its containing block on phone, so drop this here too.
			transform-style: flat;
		}
	}

	// all four discard pools live in the centre, forming a box around the middle instead of each
	// sitting at its own seat's table edge (docs/03-frontend.md §3 "Discard pool geometry") --
	// matches the physical pile-in-front-of-you layout, and the space is free now that
	// wall/prevailing moved up to `.table-status` and dealer/turn dropped out entirely
	// (`.dealer-badge`/`.seat-region--turn`'s outline on the seat headers already say both). Below
	// tablet-up
	// there's no room for a literal box, so the four pools just stack.
	.table-center {
		grid-area: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);

		@include layout.tablet-up {
			display: grid;
			grid-template-areas:
				'.    across .'
				'left .      right'
				'.    self   .';
			grid-template-columns: auto 1fr auto;
			grid-template-rows: auto 1fr auto;
			place-items: center;
		}
	}

	// centered, scrim-backed like `.panel-overlay` below -- a claim decision is as consequential
	// as a hand result, so it gets the same modal weight, not a translucent button row that
	// leaves the table interactive underneath it.
	.claim-overlay,
	.panel-overlay {
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.5);
		z-index: var(--z-modal);
		padding: var(--space-3);
	}

	// hugs whatever dialog content it wraps (ScoreSheet/Settings/game-end) so the
	// CloseButton it contains is positioned against that panel's own corner, not the fullscreen
	// scrim's.
	.panel {
		position: relative;
	}

	.confirm-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: 100%;
		max-width: 22rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		text-align: center;
		@include buttons.panel-elevated;

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}

		p {
			margin: 0;
			color: var(--color-text-muted);
		}
	}

	.confirm-actions {
		display: flex;
		justify-content: center;
		gap: var(--space-3);

		button {
			min-height: 44px;
			padding: var(--space-2) var(--space-4);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-secondary;
		}

		.confirm-leave {
			@include buttons.btn-primary;
		}
	}

	// sub-768px collapse (docs/03-frontend.md §3): opponent backs to a thin overlapping strip,
	// discard pools to horizontal scroll, your hand pinned to the safe-area bottom.
	@include layout.phone-only {
		// `.table-tilt`'s `perspective` (unconditional, for the desktop rotateX) establishes a
		// containing block for descendant `position: fixed` elements same as `transform` does --
		// YourSeatRegion's own `.seat-region--self` phone override pins to the tilted box's own
		// edge instead of the viewport's without this. Drop it here so "pinned to the true screen
		// bottom" means what it says.
		.table-tilt {
			perspective: none;
		}

		.table-surface {
			padding-bottom: 30vh; // reserve room under YourSeatRegion's fixed phone-width footer
		}
	}
</style>
