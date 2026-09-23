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
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import DialogTimer from '$lib/ui/DialogTimer.svelte';
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
	import CloseButton from '$lib/ui/CloseButton.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';
	import type { TileCode } from '$lib/table/tile-code';

	const WIND_LABEL: Record<string, string> = { E: 'East', S: 'South', W: 'West', N: 'North' };
	// table-view wind glyphs (revamp: seat/prevailing badges show these instead of the E/S/W/N
	// letter) — WIND_LABEL above stays in use for the one full-sentence spot ("You're seated as
	// East") where a bare glyph would read as unlabelled to a screen reader.
	const WIND_CHAR: Record<string, string> = { E: '東', S: '南', W: '西', N: '北' };
	const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const;

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

	// seat wind badge: the dealer holds East for the current hand, remaining seats follow
	// clockwise in seat-index space — a badge only, never position (§10 "What stays").
	function seatWind(seat: Seat): (typeof SEAT_WINDS)[number] {
		return SEAT_WINDS[(seat - gameState.dealer + 4) % 4];
	}

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

{#snippet seatRingSlot(label: string, self: boolean = false)}
	<div class="seat-ring-slot" class:seat-ring-slot--self={self}>
		<span>{label}</span>
	</div>
{/snippet}

<!-- Seated pre-game preview (docs/03-frontend.md's "/table/[id] wiring" pre-game states). Same
	across/left/right/self arrangement the real table grid uses (§3), previewed at token scale
	before any hand exists. Self is the one seat this screen already knows a real wind for (the
	dealer is fixed at table construction, before any `ready`). The other three show real live
	occupancy instead (`seatStatus`/`names`, kept current via `seat_state` broadcasts the same
	way `seatPicker` below reads them pre-join) -- so a seated player watching this screen sees
	the next arrival land, not just a placeholder that never changes. -->
{#snippet seatRing(you: Seat)}
	<div class="seat-ring" aria-hidden="true">
		<div class="seat-ring-pos seat-ring-pos--across">
			{@render seatOccupancySlot(((you + 2) % 4) as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--left">
			{@render seatOccupancySlot(((you + 3) % 4) as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--right">
			{@render seatOccupancySlot(((you + 1) % 4) as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--self">
			{@render seatRingSlot(WIND_CHAR[seatWind(you)], true)}
		</div>
	</div>
{/snippet}

{#snippet seatOccupancySlot(seat: Seat)}
	{@const status = liveStore?.state.seatStatus[seat] ?? 'empty'}
	{@const name = liveStore?.state.names[seat] ?? null}
	{@const open = status === 'empty'}
	<div class="seat-ring-slot" class:seat-ring-slot--filled={!open}>
		<span>{open ? 'Open' : status === 'bot' ? 'Bot' : (name ?? 'Taken')}</span>
	</div>
{/snippet}

<!-- Pre-join seat picker: connected as a spectator (the socket-setup effect above), so real
	`seatStatus`/`names` are already known -- unlike the old "Sit down" button (any open seat),
	each slot here is a specific seat you can click to `join` it directly. Absolute seats 0-3 are
	assigned to the same across/left/right/self layout `seatRing` uses for seat 0, purely so the
	picker's geometry doesn't jump once you're actually seated. -->
{#snippet seatPickerSlot(seat: Seat, self: boolean = false)}
	{@const status = liveStore?.state.seatStatus[seat] ?? 'empty'}
	{@const name = liveStore?.state.names[seat] ?? null}
	{@const open = status === 'empty'}
	<button
		type="button"
		class="seat-ring-slot seat-ring-slot--pickable"
		class:seat-ring-slot--self={self}
		class:seat-ring-slot--open={open}
		disabled={!open}
		onclick={() => liveStore?.socket.join(seat, displayName.trim() || undefined)}
	>
		<span>{open ? 'Open' : status === 'bot' ? 'Bot' : (name ?? 'Taken')}</span>
	</button>
{/snippet}

{#snippet seatPicker()}
	<div class="seat-ring">
		<div class="seat-ring-pos seat-ring-pos--across">
			{@render seatPickerSlot(2 as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--left">
			{@render seatPickerSlot(3 as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--right">
			{@render seatPickerSlot(1 as Seat)}
		</div>
		<div class="seat-ring-pos seat-ring-pos--self">
			{@render seatPickerSlot(0 as Seat, true)}
		</div>
	</div>
{/snippet}

{#snippet opponentRegion(seat: MockSeatState, position: 'across' | 'left' | 'right')}
	<section
		class="seat-region seat-region--{position}"
		class:seat-region--turn={seat.seat === gameState.turn}
		aria-label="{seat.name}'s seat"
	>
		<header class="seat-meta">
			<span class="seat-name">{seat.name}</span>
			<span class="seat-wind" aria-label="{WIND_LABEL[seatWind(seat.seat)]} wind"
				>{WIND_CHAR[seatWind(seat.seat)]}</span
			>
			{#if seat.seat === gameState.dealer}<span class="dealer-badge" title="Dealer">D</span>{/if}
			{#if seat.status === 'bot'}<span class="bot-badge" title="Bot-controlled seat">Bot</span>{/if}
			<span class="seat-score">{seat.score}</span>
		</header>

		<div class="seat-hand-strip seat-hand-strip--{position}">
			{#if seat.concealedHand}
				<div class="tile-row backs-row" aria-label="{seat.name}'s concealed hand">
					{#each seat.concealedHand as code, i (i)}
						<div class="mini-tile"><TileFace {code} /></div>
					{/each}
				</div>
			{:else}
				<div class="tile-row backs-row" aria-label="{seat.concealedCount} concealed tiles">
					{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
						<div class="mini-tile back"><TileFace code={null} /></div>
					{/each}
				</div>
			{/if}

			{#if seat.flowers.length || seat.melds.length}
				<div class="tile-row meld-row" aria-label="{seat.name}'s melds">
					{#if seat.flowers.length}
						<div class="meld" aria-label="{seat.name}'s flowers">
							{#each seat.flowers as code, i (i)}
								<div class="mini-tile"><TileFace {code} /></div>
							{/each}
						</div>
					{/if}
					{#each seat.melds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (ti)}
								<div class="mini-tile">
									<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	</section>
{/snippet}

<!-- All four discard pools live together in the centre (docs/03-frontend.md §3's "Discard pool
	geometry"), forming a box around the middle of the table instead of sitting at each seat's own
	edge -- matches the physical layout of discards piled in front of each player, in the shared
	space between hands. `position` picks the box side and, for left/right, the rotation that keeps
	each pool parallel to that seat's own (already-rotated) hand. -->
{#snippet centerDiscardPool(
	seat: MockSeatState,
	position: 'across' | 'left' | 'right' | 'self',
	ariaLabel: string
)}
	<div class="discard-pool discard-pool--{position}" role="list" aria-label={ariaLabel}>
		{#each seat.discards as code, i (i)}
			<div class="discard-tile" role="listitem"><TileFace {code} /></div>
		{/each}
	</div>
{/snippet}

{#if tableReady}
	<h1 class="sr-only">Table</h1>

	<div class="table-page">
		<header class="dev-toolbar">
			{#if isMock}
				<div class="scenario-picker" role="group" aria-label="Mock scenario">
					{#each MOCK_SCENARIOS as scenario (scenario.id)}
						<button
							type="button"
							class="scenario-btn"
							class:active={scenario.id === scenarioId}
							aria-pressed={scenario.id === scenarioId}
							onclick={() => (scenarioId = scenario.id)}
						>
							{scenario.label}
						</button>
					{/each}
				</div>
			{:else if spectating}
				<p class="table-label">
					Table <strong>{tableId}</strong> · spectating
				</p>
			{:else}
				<p class="table-label">
					Table <strong>{tableId}</strong> · seat {liveStore?.state.seat}{#if isPractice}
						· practice vs bots{/if}
				</p>
			{/if}

			<div class="table-status" aria-label="Table status">
				<span>Wall <strong>{gameState.wallCount}</strong></span>
				<span>Prevailing <strong>{WIND_CHAR[gameState.prevailing]}</strong></span>
			</div>

			<div class="chrome-toggles">
				<button type="button" onclick={handleLeaveClick}>Leave game</button>
				<button type="button" onclick={() => (showScoreSheet = !showScoreSheet)}>Score sheet</button
				>
				{#if !spectating}
					<button type="button" onclick={() => (showSettings = !showSettings)}>Settings</button>
				{/if}
				<button type="button" onclick={() => pushToast('Reconnecting…')}>Toast</button>
				{#if isMock}
					<button type="button" onclick={() => (showAnimationDemo = !showAnimationDemo)}
						>Animate a turn</button
					>
				{/if}
			</div>
		</header>

		<div class="table-tilt">
			<div class="table-surface" data-testid="table-scene">
				{@render opponentRegion(seatAt(2), 'across')}
				{@render opponentRegion(seatAt(3), 'left')}
				{@render opponentRegion(seatAt(1), 'right')}

				<div class="table-center">
					{@render centerDiscardPool(seatAt(2), 'across', `${seatAt(2).name}'s discards`)}
					{@render centerDiscardPool(seatAt(3), 'left', `${seatAt(3).name}'s discards`)}
					{@render centerDiscardPool(seatAt(1), 'right', `${seatAt(1).name}'s discards`)}
					{@render centerDiscardPool(
						seatAt(0),
						'self',
						spectating ? `${seatAt(0).name}'s discards` : 'Your discards'
					)}
				</div>

				<section
					class="seat-region seat-region--self"
					aria-label={spectating ? `${seatAt(0).name}'s seat` : 'Your hand'}
				>
					<header class="seat-meta">
						<span class="seat-name">{seatAt(0).name}</span>
						<span class="seat-wind" aria-label="{WIND_LABEL[seatWind(seatAt(0).seat)]} wind"
							>{WIND_CHAR[seatWind(seatAt(0).seat)]}</span
						>
						{#if seatAt(0).seat === gameState.dealer}<span class="dealer-badge" title="Dealer"
								>D</span
							>{/if}
						<div class="turn-timer">
							{#if gameState.turnDurationMs !== null}
								{#key gameState.turn}
									<TimerRing durationMs={gameState.turnDurationMs} size={24} />
								{/key}
							{/if}
						</div>
						<span class="seat-score">{seatAt(0).score}</span>
					</header>

					<div class="your-hand">
						{#if seatAt(0).flowers.length || seatAt(0).melds.length}
							<div
								class="tile-row meld-row"
								aria-label={spectating ? `${seatAt(0).name}'s melds` : 'Your melds'}
							>
								{#if seatAt(0).flowers.length}
									<div
										class="meld"
										aria-label={spectating ? `${seatAt(0).name}'s flowers` : 'Your flowers'}
									>
										{#each seatAt(0).flowers as code, i (i)}
											<div class="mini-tile"><TileFace {code} /></div>
										{/each}
									</div>
								{/if}
								{#each seatAt(0).melds as meld, mi (mi)}
									<div class="meld">
										{#each meld.tiles as code, ti (ti)}
											<div class="mini-tile">
												<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
											</div>
										{/each}
									</div>
								{/each}
							</div>
						{/if}

						<!-- spectators get the opponents' tile size: no seat here is "yours" -->
						{#if spectating && seatAt(0).concealedHand}
							<div class="tile-row backs-row" aria-label="{seatAt(0).name}'s concealed hand">
								{#each seatAt(0).concealedHand ?? [] as code, i (i)}
									<div class="mini-tile"><TileFace {code} /></div>
								{/each}
							</div>
						{:else if spectating}
							<div
								class="tile-row backs-row"
								aria-label="{seatAt(0).concealedCount} concealed tiles"
							>
								{#each Array.from({ length: seatAt(0).concealedCount }) as _, i (i)}
									<div class="mini-tile back"><TileFace code={null} /></div>
								{/each}
							</div>
						{:else}
							<div class="hand-row" aria-label="Your concealed hand">
								{#each ownHandTiles as tile (tile.key)}
									{#if !isMock && tile.tileId !== null && discardableTileIds.has(tile.tileId)}
										<button
											type="button"
											class="hand-tile hand-tile-btn"
											class:hand-tile--drawn={tile.drawn}
											aria-label="Discard {tile.code}"
											onclick={() => discardTile(tile.tileId)}
										>
											<TileFace code={tile.code} />
										</button>
									{:else}
										<div class="hand-tile" class:hand-tile--drawn={tile.drawn}>
											<TileFace code={tile.code} />
										</div>
									{/if}
								{/each}
							</div>
						{/if}

						{#if declareOptions.length}
							<div class="declare-actions" role="group" aria-label="Declare options">
								{#each declareOptions as opt (opt.key)}
									<button type="button" onclick={opt.onClick}>{opt.label}</button>
								{/each}
							</div>
						{/if}
					</div>
				</section>
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
			<div class="faan-overlay" data-testid="faan-overlay">
				{#key gameState.handNo}
					<div class="hand-end-timer">
						<DialogTimer
							durationMs={gameState.handEndHoldMs ?? 0}
							size={40}
							onClose={dismissHandEnd}
						/>
					</div>
				{/key}
				<div class="panel">
					<CloseButton onclick={dismissHandEnd} />
					{#if gameState.handResult.outcome === 'win'}
						<FaanBreakdown
							winner={gameState.handResult.winner as 0 | 1 | 2 | 3}
							{seatNames}
							winningHand={gameState.handResult.winningHand ?? []}
							melds={gameState.seats[gameState.handResult.winner as 0 | 1 | 2 | 3].melds}
							patterns={gameState.handResult.patterns ?? []}
							totalFaan={gameState.handResult.totalFaan ?? 0}
							payments={gameState.handResult.payments ?? {}}
						/>
					{:else}
						<section class="hand-end-summary" data-testid="hand-end-draw" aria-label="Hand result">
							<h2>Hand {gameState.handNo}</h2>
							<p>Draw</p>
						</section>
					{/if}
				</div>
			</div>
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
			<div class="panel-overlay">
				<div class="panel">
					<CloseButton onclick={() => (showScoreSheet = false)} />
					<ScoreSheet
						seats={scoreSeats}
						totals={scoreTotals}
						hands={scoreHands}
						standings={scoreStandings}
					/>
				</div>
			</div>
		{/if}

		{#if showSettings}
			<div class="panel-overlay">
				<div class="panel">
					<CloseButton onclick={() => (showSettings = false)} />
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
				</div>
			</div>
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
				{@render seatPicker()}
			{:else}
				{@render seatRing(effectiveSeat as Seat)}
				<h2>You're seated as {WIND_LABEL[seatWind(effectiveSeat as Seat)]}</h2>
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

	// seat preview ring: across/left/right/self, same relative arrangement as the real table
	// grid (§3, layout.seat-region-grid) at token scale -- foreshadows the seats you're about
	// to sit at rather than inventing a second layout language for the pre-game screen.
	.seat-ring {
		display: grid;
		grid-template-areas:
			'.      across .'
			'left   .      right'
			'.      self   .';
		grid-template-columns: repeat(3, 3.25rem);
		grid-template-rows: repeat(3, 3.25rem);
		gap: var(--space-1);
		place-items: center;
	}

	.seat-ring-pos--across {
		grid-area: across;
	}

	.seat-ring-pos--left {
		grid-area: left;
	}

	.seat-ring-pos--right {
		grid-area: right;
	}

	.seat-ring-pos--self {
		grid-area: self;
	}

	.seat-ring-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 50%;
		border: 1px dashed var(--color-border);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		// "waiting, alive" -- the base/default treatment for a genuinely open seat
		// (server/app/table.py's `_seat_status_tuple` reports `empty` for one, distinct from
		// `connected`/`bot`/`disconnected`/`autoplay`), so this animation now means what it
		// looks like: nobody's here yet, but the table is open and listening.
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// occupancy is real (see above) -- a filled seat reads solid/inert rather than still
	// breathing "open," same visual language `.seat-ring-slot--self` already uses.
	.seat-ring-slot--filled {
		border: 1px solid var(--color-border);
		color: var(--color-text);
		animation: none;
	}

	// the one seat this screen actually knows something real about: dealer is fixed at table
	// creation, so once you're seated your own wind is true today, not a guess.
	.seat-ring-slot--self {
		border: 1px solid var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 16%, transparent);
		color: var(--color-text);
		animation: none;
	}

	@keyframes seat-ring-breathe {
		0%,
		100% {
			opacity: 0.5;
		}
		50% {
			opacity: 1;
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.seat-ring-slot {
			animation: none;
			opacity: 0.85;
		}
	}

	// the picker knows real occupancy (spectator `state_sync`, unlike `.seat-ring-slot`'s own
	// "can't tell" note above), so a taken seat reads as solid/inert rather than breathing, and
	// an open one is a real, obviously-clickable button.
	.seat-ring-slot--pickable {
		font: inherit;
		background: none;
		animation: none;
		opacity: 1;

		&:disabled {
			cursor: default;
			opacity: 0.7;
		}
	}

	.seat-ring-slot--open {
		border: 1px solid var(--color-accent);
		color: var(--color-text);
		cursor: pointer;

		&:hover {
			background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		}
	}

	.pretable-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.dev-toolbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-3);
		z-index: var(--z-hud);
	}

	.scenario-picker,
	.chrome-toggles {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.scenario-btn,
	.chrome-toggles button {
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
	}

	// inactive scenario tabs are tertiary — only the active one should draw the eye.
	.scenario-btn {
		@include buttons.btn-ghost;
	}

	.scenario-btn.active {
		@include buttons.btn-primary;
	}

	.chrome-toggles button {
		@include buttons.btn-secondary;
	}

	.table-label {
		margin: 0;
		align-self: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	// wall/prevailing: was `.center-info` on the table surface itself (see `.table-center`
	// below for what took its place there) -- dealer/turn moved with it but aren't reproduced
	// here, since `.dealer-badge`/`.seat-region--turn`'s outline on each seat already say that.
	.table-status {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;

		strong {
			color: var(--color-text);
		}
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

	.seat-region {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-width: 0;
		min-height: 0;
	}

	.seat-region--across {
		grid-area: across;
	}

	.seat-region--left {
		grid-area: left;
	}

	.seat-region--right {
		grid-area: right;
	}

	.seat-region--self {
		grid-area: self;
	}

	.seat-region--turn {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
		border-radius: var(--radius-sm);
	}

	.seat-meta {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.seat-name {
		font-weight: 600;
	}

	.seat-wind {
		color: var(--color-text-muted);
	}

	// fixed footprint (matches the `TimerRing size={24}` passed above) so the header doesn't
	// reflow -- `seat-score`'s `margin-inline-start: auto` shifts position with any preceding
	// sibling that mounts/unmounts, and this one toggles every time the turn changes.
	.turn-timer {
		width: 24px;
		height: 24px;
		pointer-events: none;
	}

	.dealer-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.25rem;
		height: 1.25rem;
		border-radius: 50%;
		background: var(--color-accent);
		color: var(--color-text);
		font-size: 0.7rem;
		font-weight: 700;
	}

	// bot-controlled seat (M4.5 practice mode) -- a persistent identity marker, not a transient
	// state like dealer/turn, so it reads as a quiet chip rather than borrowing --color-accent.
	.bot-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 1.25rem;
		padding: 0 0.4rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
		font-size: 0.65rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.seat-score {
		margin-inline-start: auto;
		font-variant-numeric: tabular-nums;
		color: var(--color-text-muted);
	}

	.seat-hand-strip {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.tile-row {
		display: flex;
		gap: 2px;
		flex-wrap: wrap;
	}

	.mini-tile {
		height: clamp(24px, 4vw, 36px);
	}

	.mini-tile :global(.tile-face) {
		height: 100%;
	}

	.meld {
		display: flex;
		gap: 1px;
		margin-inline-end: var(--space-2);
	}

	// vertical strip along the table edge (docs/03-frontend.md §3): `writing-mode` alone reflows
	// the flex axes (a row's main axis becomes the block-progression axis) so the box's own
	// width/height already account for the vertical footprint, unlike `transform: rotate()`,
	// which only repaints the box in place and leaves the parent grid cell sized for the
	// original unrotated (horizontal) footprint — that mismatch is what let the strip's content
	// escape `.seat-region--left/--right` into whatever sat past the grid's edge.
	.seat-hand-strip--left {
		@include layout.tablet-up {
			writing-mode: vertical-lr;
		}
	}

	.seat-hand-strip--right {
		@include layout.tablet-up {
			writing-mode: vertical-rl;
		}
	}

	// tiles themselves rotated 90° to face the table, same physical read as a real side seat.
	// The mismatch that ruled out `transform: rotate()` on the *strip* above is still real, so
	// it isn't reused here at the tile level either: `.mini-tile` keeps its normal (unrotated)
	// box for layout purposes, already sized to the rotated footprint (width/height swapped from
	// the portrait default) — the swap is what the grid/flex ancestors measure. Only the
	// `.tile-face` inside is rotated, absolutely positioned off that stable box so the rotation
	// is paint-only and never changes what its ancestors reserve space for.
	.seat-hand-strip--left .mini-tile,
	.seat-hand-strip--right .mini-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(24px, 4vw, 36px);
			height: calc(clamp(24px, 4vw, 36px) * 3 / 4);
		}
	}

	.seat-hand-strip--left .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.seat-hand-strip--right .mini-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(24px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 28px));
		justify-content: start;
		gap: 2px;
		max-width: 14rem;
	}

	.discard-tile {
		height: clamp(22px, 3.5vw, 32px);
	}

	.discard-tile :global(.tile-face) {
		height: 100%;
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

	.table-center .discard-pool--across {
		@include layout.tablet-up {
			grid-area: across;
		}
	}

	.table-center .discard-pool--left {
		@include layout.tablet-up {
			grid-area: left;
		}
	}

	.table-center .discard-pool--right {
		@include layout.tablet-up {
			grid-area: right;
		}
	}

	.table-center .discard-pool--self {
		@include layout.tablet-up {
			grid-area: self;
		}
	}

	// tablet-up only: below that, the phone-collapse block further down (`.discard-pool`'s
	// horizontal-scroll override) needs to win, and it matches these pools the same as any other
	// via the plain `.discard-pool` class -- gating this to tablet-up keeps that override's
	// lower-specificity `.discard-pool` selector from silently losing to these on phone.
	// wider than the 6-column default so a long hand's discards wrap onto fewer rows -- unbounded
	// row growth here pushes `.seat-region--self` (`auto`-height row below `center`) down the page,
	// off-screen, since `.table-center`'s own middle column is `1fr` and has room to spare.
	.table-center .discard-pool {
		@include layout.tablet-up {
			grid-template-columns: repeat(12, minmax(20px, 28px));
			max-width: 26rem;
		}
	}

	.table-center .discard-tile {
		@include layout.tablet-up {
			height: clamp(26px, 4vw, 36px);
		}
	}

	// left/right box pools rotated to read parallel to that seat's own already-rotated hand strip
	// -- same box-stays-put/only-the-face-rotates technique as `.seat-hand-strip--left/--right
	// .mini-tile` above (paint-only rotation, never changes what the grid measures), reused here
	// for a grid of discards instead of a flex row of hand tiles. Declared after the shared
	// `.table-center .discard-pool`/`.discard-tile` rules above so these equal-specificity
	// overrides win on `grid-template-columns`/height.
	.table-center .discard-pool--left,
	.table-center .discard-pool--right {
		@include layout.tablet-up {
			grid-template-columns: none;
			grid-template-rows: repeat(6, minmax(24px, 32px));
			grid-auto-flow: column;
		}
	}

	.table-center .discard-pool--left .discard-tile,
	.table-center .discard-pool--right .discard-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(26px, 4vw, 36px);
			height: calc(clamp(26px, 4vw, 36px) * 3 / 4);
		}
	}

	.table-center .discard-pool--left .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(26px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.table-center .discard-pool--right .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(26px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	.your-hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.hand-row {
		display: flex;
		gap: 2px;
	}

	.hand-tile {
		height: clamp(48px, 9vw, 84px);
	}

	.hand-tile :global(.tile-face) {
		height: 100%;
	}

	.hand-tile--drawn {
		margin-inline-start: var(--space-4);
	}

	// live-mode-only interactive hand tile: same box as the plain `.hand-tile` div (kept a
	// button only when there's a discard to send it) -- a button reset, not a second style.
	.hand-tile-btn {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;

		&:focus-visible {
			outline: 2px solid var(--color-accent);
			outline-offset: 2px;
		}
	}

	.declare-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);

		button {
			min-height: 44px;
			padding: var(--space-2) var(--space-3);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-primary;

			// `btn-primary`'s `:active` press (`translateY(3px)`) moves the button out from under
			// a held-then-released pointer before mouseup's hit-test runs, so mouseup/click lands
			// on this flex row's own `<div>` instead of the button -- Svelte's click delegation
			// walks up from the real event target and never reaches the button's handler, so the
			// declare action (win/kong) silently never sends. No visible-position feedback lost:
			// `:hover`'s background swap still shows the press.
			&:active:not(:disabled) {
				transform: none;
			}
		}
	}

	// centered, scrim-backed like `.faan-overlay`/`.panel-overlay` below -- a claim decision is
	// as consequential as a hand result, so it gets the same modal weight, not a translucent
	// button row that leaves the table interactive underneath it.
	.claim-overlay,
	.faan-overlay,
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

	.faan-overlay {
		flex-direction: column;
		gap: var(--space-3);
	}

	.hand-end-summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		// wide enough that a short heading (e.g. "Hand 6") never sits under the CloseButton in
		// the panel's top-right corner
		min-width: 14rem;
		max-width: 24rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
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

	// hugs whatever dialog content it wraps (ScoreSheet/Settings/hand-end result) so the
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
		.seat-hand-strip--left,
		.seat-hand-strip--right,
		.seat-hand-strip--across {
			flex-direction: row;
		}

		.backs-row .mini-tile.back {
			margin-inline-end: -14px; // overlapping-backs strip, count-only

			&:last-child {
				margin-inline-end: 0;
			}
		}

		.discard-pool {
			grid-template-columns: none;
			grid-auto-flow: column;
			grid-auto-columns: minmax(22px, 28px);
			overflow-x: auto;
			max-width: 100%;
		}

		// `.table-tilt`'s `perspective` (unconditional, for the desktop rotateX) establishes a
		// containing block for descendant `position: fixed` elements same as `transform` does --
		// left in place, `.seat-region--self` below pins to the tilted box's own edge instead of
		// the viewport's. Drop it here so "pinned to the true screen bottom" means what it says.
		.table-tilt {
			perspective: none;
		}

		.seat-region--self {
			position: fixed;
			inset-inline: 0;
			bottom: 0;
			background: var(--color-surface);
			border-top: 1px solid var(--color-border);
			padding: var(--space-2) var(--space-2) max(var(--space-2), env(safe-area-inset-bottom));
			z-index: var(--z-hud);
		}

		.table-surface {
			padding-bottom: 30vh; // reserve room under the fixed self region above
		}

		.hand-tile {
			height: clamp(44px, 12vw, 60px);
		}

		// a full hand at this tile size is wider than a phone screen, and `.seat-region--self` is
		// `position: fixed` (no scrollable ancestor) -- without this, tiles past the edge are
		// simply unreachable rather than scrolled-to, same as `.discard-pool` above.
		.hand-row {
			overflow-x: auto;
		}
	}
</style>
