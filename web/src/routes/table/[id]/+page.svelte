<script lang="ts">
	import { page } from '$app/state';
	import TileFace from '$lib/table/TileFace.svelte';
	import {
		MOCK_SCENARIOS,
		relativeSeat,
		type MockMeld,
		type MockSeatState,
		type Seat
	} from '$lib/table/mock-game-state';
	import { tileIdToCode } from '$lib/table/tile-code';
	import { viewFromClientState, wireWindToCode } from '$lib/table/live-view';
	import { MahjongSocket, defaultWsUrl } from '$lib/net/socket';
	import { GameStore } from '$lib/game/store.svelte';
	import type { ClientGameState, ConnectionStatus } from '$lib/game/state';
	import type { ServerEvent } from '$lib/net/protocol';
	import ClaimDialog from '$lib/ui/ClaimDialog.svelte';
	import type { ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from '$lib/ui/ScoreSheet.svelte';
	import Chat, { type ChatEntry } from '$lib/ui/Chat.svelte';
	import Settings, { type AutoArm, type ClientPrefs } from '$lib/ui/Settings.svelte';
	import {
		loadAutoArm,
		loadClientPrefs,
		loadDisplayName,
		saveAutoArm,
		saveClientPrefs,
		saveDisplayName
	} from '$lib/ui/settings-storage';
	import Toast from '$lib/ui/Toast.svelte';
	import CloseButton from '$lib/ui/CloseButton.svelte';
	import { createToast, removeToast, type ToastEntry } from '$lib/ui/toasts';
	import {
		initialSlotState,
		popSlotForDiscard,
		popSlotsForConcealedKong,
		pushDrawnSlot,
		type SlotState
	} from '$lib/table/tile-slots';
	import type { TileCode } from '$lib/table/tile-code';

	const WIND_LABEL: Record<string, string> = { E: 'East', S: 'South', W: 'West', N: 'North' };
	const SEAT_WINDS = ['E', 'S', 'W', 'N'] as const;

	// --- mock vs. live (docs/03-frontend.md §6's WS/reducer/store plumbing, wired into this
	// route) -----------------------------------------------------------------------------------
	// `?mock=<scenarioId>` (any value, or bare `?mock`) renders a frozen MOCK_SCENARIOS fixture
	// -- the screenshot workflow (.claude/skills/frontend-screenshots/SKILL.md) and design
	// iteration need this to keep working with no backend running. Omitted, `[id]` is treated as
	// a real room id and this opens a real MahjongSocket -> GameStore against it. Both paths
	// render through the same MockGameState-shaped view model (`gameState` below) so the
	// template/component tree never forks (`$lib/table/live-view.ts`'s module doc).
	let isMock = $derived(page.url.searchParams.has('mock'));
	let roomId = $derived(page.params.id ?? '');

	// `?practice=1` (this route's own query param, set by the lobby's "Play vs bots" button --
	// spelling is unrelated to the wire's own `&practice=true`) opens the live socket in M4.5
	// practice mode: seats 1-3 are bot-bound at room *creation* (server/app/ws.py's
	// `ws_endpoint`/`app/room.py`'s `Room.__init__(practice=...)`), so the human's own `join`
	// (still a real intent, same "Sit down" flow below) is the only one this page ever sends.
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
	// there's no backend "has this room actually started" field (state_sync's own snapshot
	// already reflects a fully-dealt hand the instant the room is created -- mahjong_core's
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

	// discrete events that only exist once `Room.started` (app/room.py) -- unlike a state_sync
	// snapshot, these can't have been computed ahead of the room actually dealing/turning.
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
		const practiceParam = isPractice ? '&practice=true' : '';
		const socket = new MahjongSocket(
			`${defaultWsUrl()}?room=${encodeURIComponent(roomId)}${practiceParam}`
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
			if (event.t === 'error') {
				pushToast(`Server error: ${event.d.message}`);
			}
		});
		socket.connect();
		return () => {
			offEvent();
			store.destroy();
			socket.disconnect();
			liveStore = null;
		};
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

	let live = $derived(!isMock && liveStore ? viewFromClientState(liveStore.state) : null);
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
				handEverStarted)
	);

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

	// --- pre-game invite link (live mode only) ----------------------------------------------
	// the room's URL *is* the invite -- whoever opens it lands in this same room (docs/03
	// -frontend.md's "/table/[id] wiring": [id] is a real room id, auto-created on first
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
	// mock mode has no real hand_end_ack round trip to hide the overlay behind -- dismissing
	// there just closes it locally, reset whenever the scenario picker jumps to a fresh one.
	let mockHandEndDismissed = $state(false);
	$effect(() => {
		void scenarioId;
		mockHandEndDismissed = false;
	});

	function dismissHandEnd(): void {
		if (isMock) {
			mockHandEndDismissed = true;
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

	// minimal chrome to prove ScoreSheet/Chat/Settings/Toast compose into the scene without
	// layout collision (this sub-task's scope) — not the final chrome, just reachability.
	let showScoreSheet = $state(false);
	let showChat = $state(false);
	let showSettings = $state(false);

	let scoreSeats: SeatInfo[] = $derived(
		gameState.seats.map((s) => ({ seat: s.seat as SeatInfo['seat'], name: s.name }))
	);
	let scoreTotals: Totals = $derived(
		Object.fromEntries(gameState.seats.map((s) => [s.seat, s.score])) as Totals
	);
	// Mock path: MOCK_SCENARIOS is always one frozen, already-dealt hand (no real hand_end
	// stream behind it), so a single row synthesized from the current snapshot is the correct
	// (and only possible) rendering here — unchanged by the live-history work below.
	// Live path: real accumulated history off `handHistory` (lib/game/state.ts), built by
	// lib/net/reducer.ts from every `hand_end` this session has actually seen — growing across a
	// live multi-hand game rather than showing just the latest hand.
	let scoreHands: HandRecord[] = $derived(
		isMock
			? [
					{
						handNo: gameState.handNo,
						dealer: gameState.dealer as HandRecord['dealer'],
						prevailing: gameState.prevailing,
						deltas: gameState.handResult?.payments ?? {}
					}
				]
			: (liveStore?.state.handHistory.map((h): HandRecord => ({
					handNo: h.handNo,
					dealer: h.dealer as HandRecord['dealer'],
					prevailing: wireWindToCode(h.prevailing),
					deltas: (h.payments ?? {}) as HandRecord['deltas']
				})) ?? [])
	);

	// `game_end` (docs/02-protocol.md §3) is a terminal, fires-once event carrying only
	// `{hand_no, scores}` — absolute final totals, no placement rules. Ranking by raw total is
	// the "straightforward" case ScoreSheet.svelte's `standings` doc comment calls out; anything
	// beyond that (tiebreak rules, etc.) isn't specified on the wire, so this doesn't invent one
	// beyond a deterministic seat-order tiebreak. Mock path never has a real `game_end`, so this
	// stays unset there, same as before.
	let scoreStandings: Standing[] | undefined = $derived(
		!isMock && liveStore?.state.gameEnd
			? liveStore.state.gameEnd.scores
					.map((total, seat) => ({ seat: seat as Standing['seat'], total }))
					.sort((a, b) => b.total - a.total || a.seat - b.seat)
			: undefined
	);

	let chatMessages: ChatEntry[] = $state(
		page.url.searchParams.has('mock')
			? [{ seat: 1, phrase: 'Good game', ts: Date.now() - 60_000 }]
			: []
	);
	function sendChat(phrase: string): void {
		chatMessages = [...chatMessages, { seat: 0, phrase, ts: Date.now() }];
		// rate-limited server-side; not yet rebroadcast to other seats (server/app/ws.py's
		// `_apply_chat` comment) -- sent anyway so this is a real intent, not a dead end, and the
		// local echo above is what lets you see your own message today.
		if (!isMock) liveStore?.socket.chat(phrase);
	}

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

	// --- Live animation demo (this sub-task) ------------------------------------------------
	// A sandbox independent of the 3 static scenarios above: proves the positional
	// slot-identity mechanics (tile-slots.ts, docs/03-frontend.md §4) and the
	// transform/opacity-only transition contract (§2) actually work end to end, rather than
	// being implemented but unreachable. No JS ticker anywhere here — every animation is a CSS
	// transition/animation driven by a class or DOM-insertion, and `ontransitionend` (not a
	// timer standing in for the animation) is what commits the data change once a flight
	// actually finishes.
	let showAnimationDemo = $state(false);

	const DEMO_REVEAL_POOL: TileCode[] = ['5s', '3p', '7m', 'z1', '9p', 'z5', '4s', '2m'];
	let demoRevealIndex = $state(0);
	function nextRevealedTile(): TileCode {
		const code = DEMO_REVEAL_POOL[demoRevealIndex % DEMO_REVEAL_POOL.length];
		demoRevealIndex += 1;
		return code;
	}

	let demoOpponentSlots: SlotState = $state(initialSlotState(13));
	let demoOpponentDiscards: TileCode[] = $state([]);
	let demoOpponentMelds: MockMeld[] = $state([]);
	let leavingOpponentSlotKey: number | null = $state(null);
	let leavingOpponentTile: TileCode | null = $state(null);

	// same element (keyed by slot.key) throughout back -> revealed-and-leaving -> gone, per
	// §4's "element continuity for the CSS transition" -- appending the departed slot back at
	// its old (last) position rather than letting it disappear from the each-block early.
	let renderedOpponentSlots = $derived(
		leavingOpponentSlotKey !== null
			? [...demoOpponentSlots.slots, { key: leavingOpponentSlotKey }]
			: demoOpponentSlots.slots
	);

	function demoOpponentDraw(): void {
		demoOpponentSlots = pushDrawnSlot(demoOpponentSlots);
	}

	function demoOpponentDiscard(): void {
		if (leavingOpponentSlotKey !== null) return; // one flight at a time
		if (demoOpponentSlots.slots.length === 0) return;
		const { left, remaining } = popSlotForDiscard(demoOpponentSlots);
		leavingOpponentTile = nextRevealedTile(); // morphs face-up immediately (§4)
		leavingOpponentSlotKey = left.key;
		demoOpponentSlots = remaining;
	}

	function commitOpponentDiscard(): void {
		if (leavingOpponentSlotKey === null || leavingOpponentTile === null) return;
		demoOpponentDiscards = [...demoOpponentDiscards, leavingOpponentTile];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
	}

	function demoOpponentConcealedKong(): void {
		if (demoOpponentSlots.slots.length < 4) return;
		const { remaining } = popSlotsForConcealedKong(demoOpponentSlots);
		demoOpponentSlots = remaining;
		// morphs in place -- no flight, the tiles never leave the seat (§4).
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'concealed_kong', tiles: ['1m', '1m', '1m', '1m'] }
		];
	}

	function demoOpponentClaim(): void {
		// last discarded tile claimed into an exposed pung -- the discard-pool -> meld flight
		// path, independent of the concealed-slot logic above (this tile is already revealed).
		if (demoOpponentDiscards.length === 0) return;
		const claimed = demoOpponentDiscards[demoOpponentDiscards.length - 1];
		demoOpponentDiscards = demoOpponentDiscards.slice(0, -1);
		demoOpponentMelds = [
			...demoOpponentMelds,
			{ kind: 'pung', tiles: [claimed, claimed, claimed], fromSeat: 0 }
		];
	}

	interface DemoTile {
		id: number;
		code: TileCode;
	}
	let demoTileIdSeed = 0;
	function demoTile(code: TileCode): DemoTile {
		demoTileIdSeed += 1;
		return { id: demoTileIdSeed, code };
	}
	let demoYourHand: DemoTile[] = $state([
		demoTile('1m'),
		demoTile('9s'),
		demoTile('z5'),
		demoTile('3p'),
		demoTile('7m')
	]);
	let demoYourDiscards: DemoTile[] = $state([]);
	let leavingYourTileId: number | null = $state(null);

	function demoYourDiscard(id: number): void {
		if (leavingYourTileId !== null) return;
		leavingYourTileId = id;
	}

	function commitYourDiscard(): void {
		if (leavingYourTileId === null) return;
		const tile = demoYourHand.find((t) => t.id === leavingYourTileId);
		demoYourHand = demoYourHand.filter((t) => t.id !== leavingYourTileId);
		if (tile) demoYourDiscards = [...demoYourDiscards, tile];
		leavingYourTileId = null;
	}

	function resetAnimationDemo(): void {
		demoOpponentSlots = initialSlotState(13);
		demoOpponentDiscards = [];
		demoOpponentMelds = [];
		leavingOpponentSlotKey = null;
		leavingOpponentTile = null;
		demoYourHand = [demoTile('1m'), demoTile('9s'), demoTile('z5'), demoTile('3p'), demoTile('7m')];
		demoYourDiscards = [];
		leavingYourTileId = null;
	}
</script>

{#snippet seatRingSlot(label: string, self: boolean = false)}
	<div class="seat-ring-slot" class:seat-ring-slot--self={self}>
		<span>{label}</span>
	</div>
{/snippet}

<!-- Pre-game seat preview (docs/03-frontend.md's "/table/[id] wiring" pre-game states). Same
	across/left/right/self arrangement the real table grid uses (§3), previewed at token scale
	before any hand exists. `you === null` (not seated yet) shows four identical "Open" seats --
	there is genuinely nothing else true to say pre-join. Seated, every seat's *wind* is already
	real (the dealer is fixed at room creation, before any `ready` -- docs/03-frontend.md's
	"There is no backend has this room started field" note) even though which seats are actually
	occupied is not: `seat_status` reads every unbound seat as "connected", identical to a seat
	that really is (`server/app/room.py`'s `_seat_status_tuple` docstring) -- so this deliberately
	never claims occupancy for a seat that isn't yours. -->
{#snippet seatRing(you: Seat | null)}
	<div class="seat-ring" aria-hidden="true">
		<div class="seat-ring-pos seat-ring-pos--across">
			{@render seatRingSlot(you !== null ? seatWind(((you + 2) % 4) as Seat) : 'Open')}
		</div>
		<div class="seat-ring-pos seat-ring-pos--left">
			{@render seatRingSlot(you !== null ? seatWind(((you + 3) % 4) as Seat) : 'Open')}
		</div>
		<div class="seat-ring-pos seat-ring-pos--right">
			{@render seatRingSlot(you !== null ? seatWind(((you + 1) % 4) as Seat) : 'Open')}
		</div>
		<div class="seat-ring-pos seat-ring-pos--self">
			{@render seatRingSlot(you !== null ? seatWind(you) : 'Open', you !== null)}
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
			<span class="seat-wind" title="seat wind">{seatWind(seat.seat)}</span>
			{#if seat.seat === gameState.dealer}<span class="dealer-badge" title="Dealer">D</span>{/if}
			{#if seat.seat === gameState.turn}<span class="turn-badge" title="Current turn">turn</span
				>{/if}
			{#if seat.status === 'bot'}<span class="bot-badge" title="Bot-controlled seat (FaanBot)"
					>Bot</span
				>{/if}
			<span class="seat-score">{seat.score}</span>
		</header>

		<div class="seat-hand-strip seat-hand-strip--{position}">
			{#if seat.flowers.length}
				<div class="tile-row flower-row" aria-label="{seat.name}'s flowers">
					{#each seat.flowers as code, i (i)}
						<div class="mini-tile"><TileFace {code} /></div>
					{/each}
				</div>
			{/if}

			<div class="tile-row backs-row" aria-label="{seat.concealedCount} concealed tiles">
				{#each Array.from({ length: seat.concealedCount }) as _, i (i)}
					<div class="mini-tile back"><TileFace code={null} /></div>
				{/each}
			</div>

			{#if seat.melds.length}
				<div class="tile-row meld-row" aria-label="{seat.name}'s melds">
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

		<div
			class="discard-pool discard-pool--{position}"
			role="list"
			aria-label="{seat.name}'s discards"
		>
			{#each seat.discards as code, i (i)}
				<div class="discard-tile" role="listitem"><TileFace {code} /></div>
			{/each}
		</div>
	</section>
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
			{:else}
				<p class="room-label">
					Room <strong>{roomId}</strong> · seat {liveStore?.state.seat}{#if isPractice}
						· practice vs FaanBot{/if}
				</p>
			{/if}

			<div class="chrome-toggles">
				<button type="button" onclick={() => (showScoreSheet = !showScoreSheet)}>Score sheet</button
				>
				<button type="button" onclick={() => (showChat = !showChat)}>Chat</button>
				<button type="button" onclick={() => (showSettings = !showSettings)}>Settings</button>
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

				<div class="center-info" aria-label="Table status">
					<p class="wall-count">Wall <strong>{gameState.wallCount}</strong></p>
					<p>Prevailing <strong>{WIND_LABEL[gameState.prevailing]}</strong></p>
					<p>Dealer <strong>{gameState.seats[gameState.dealer].name}</strong></p>
					<p>Turn <strong>{gameState.seats[gameState.turn].name}</strong></p>
				</div>

				<section class="seat-region seat-region--self" aria-label="Your hand">
					<header class="seat-meta">
						<span class="seat-name">{seatAt(0).name}</span>
						<span class="seat-wind" title="seat wind">{seatWind(seatAt(0).seat)}</span>
						{#if seatAt(0).seat === gameState.dealer}<span class="dealer-badge" title="Dealer"
								>D</span
							>{/if}
						{#if seatAt(0).seat === gameState.turn}<span class="turn-badge" title="Current turn"
								>turn</span
							>{/if}
						<span class="seat-score">{seatAt(0).score}</span>
					</header>

					<div class="your-hand">
						{#if seatAt(0).flowers.length}
							<div class="tile-row flower-row" aria-label="Your flowers">
								{#each seatAt(0).flowers as code, i (i)}
									<div class="mini-tile"><TileFace {code} /></div>
								{/each}
							</div>
						{/if}

						{#if seatAt(0).melds.length}
							<div class="tile-row meld-row" aria-label="Your melds">
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

						{#if declareOptions.length}
							<div class="declare-actions" role="group" aria-label="Declare options">
								{#each declareOptions as opt (opt.key)}
									<button type="button" onclick={opt.onClick}>{opt.label}</button>
								{/each}
							</div>
						{/if}
					</div>

					<div class="discard-pool discard-pool--self" role="list" aria-label="Your discards">
						{#each seatAt(0).discards as code, i (i)}
							<div class="discard-tile" role="listitem"><TileFace {code} /></div>
						{/each}
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

		{#if gameState.handResult && !(isMock && mockHandEndDismissed)}
			<div class="faan-overlay" data-testid="faan-overlay">
				{#key gameState.handNo}
					<div class="hand-end-timer">
						<TimerRing durationMs={gameState.handEndHoldMs ?? 0} size={40} />
					</div>
				{/key}
				<div class="panel">
					<CloseButton onclick={dismissHandEnd} />
					{#if gameState.handResult.outcome === 'win'}
						<FaanBreakdown
							winner={gameState.handResult.winner as 0 | 1 | 2 | 3}
							winningHand={gameState.handResult.winningHand ?? []}
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

		{#if showChat}
			<div class="panel-overlay">
				<div class="panel">
					<CloseButton onclick={() => (showChat = false)} />
					<Chat messages={chatMessages} onSend={sendChat} />
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
			<div class="panel-overlay" data-testid="animation-demo">
				<div class="animation-demo">
					<CloseButton onclick={() => (showAnimationDemo = false)} />
					<h2>Animate a turn</h2>
					<p class="demo-hint">
						Sandboxed mock, independent of the scenarios above — proves the positional slot-identity
						mechanics and CSS-only transitions.
					</p>

					<section aria-label="Opponent seat">
						<h3>Bob (opponent)</h3>
						<div class="tile-row backs-row" aria-label="Bob's concealed tiles">
							{#each renderedOpponentSlots as slot (slot.key)}
								<div
									class="mini-tile back demo-slot"
									class:demo-tile-leaving={slot.key === leavingOpponentSlotKey}
									ontransitionend={slot.key === leavingOpponentSlotKey
										? commitOpponentDiscard
										: undefined}
								>
									<TileFace
										code={slot.key === leavingOpponentSlotKey ? leavingOpponentTile : null}
									/>
								</div>
							{/each}
						</div>
						{#if demoOpponentMelds.length}
							<div class="tile-row meld-row" aria-label="Bob's melds">
								{#each demoOpponentMelds as meld, mi (mi)}
									<div class="meld demo-meld-entering">
										{#each meld.tiles as code, ti (ti)}
											<div class="mini-tile">
												<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
											</div>
										{/each}
									</div>
								{/each}
							</div>
						{/if}
						<div class="discard-pool" role="list" aria-label="Bob's discards">
							{#each demoOpponentDiscards as code, i (i)}
								<div class="discard-tile" role="listitem"><TileFace {code} /></div>
							{/each}
						</div>
						<div class="demo-actions">
							<button type="button" onclick={demoOpponentDraw}>Draw</button>
							<button
								type="button"
								onclick={demoOpponentDiscard}
								disabled={leavingOpponentSlotKey !== null || demoOpponentSlots.slots.length === 0}
							>
								Discard
							</button>
							<button
								type="button"
								onclick={demoOpponentConcealedKong}
								disabled={demoOpponentSlots.slots.length < 4}
							>
								Concealed kong
							</button>
							<button
								type="button"
								onclick={demoOpponentClaim}
								disabled={demoOpponentDiscards.length === 0}
							>
								You claim last discard (pung)
							</button>
						</div>
					</section>

					<section aria-label="Your seat">
						<h3>You</h3>
						<div class="hand-row" aria-label="Your demo hand" data-testid="demo-your-hand">
							{#each demoYourHand as tile (tile.id)}
								<button
									type="button"
									class="hand-tile demo-hand-tile"
									class:demo-tile-leaving={tile.id === leavingYourTileId}
									disabled={leavingYourTileId !== null}
									aria-label="Discard {tile.code}"
									onclick={() => demoYourDiscard(tile.id)}
									ontransitionend={tile.id === leavingYourTileId ? commitYourDiscard : undefined}
								>
									<TileFace code={tile.code} />
								</button>
							{/each}
						</div>
						<div
							class="discard-pool discard-pool--self"
							role="list"
							aria-label="Your discards"
							data-testid="demo-your-discards"
						>
							{#each demoYourDiscards as tile (tile.id)}
								<div class="discard-tile" role="listitem"><TileFace code={tile.code} /></div>
							{/each}
						</div>
					</section>

					<button type="button" class="demo-reset" onclick={resetAnimationDemo}>Reset demo</button>
				</div>
			</div>
		{/if}

		<div class="toast-stack">
			{#each toastQueue as toast (toast.id)}
				<Toast
					message={toast.message}
					durationMs={toast.durationMs}
					onDismiss={() => dismissToast(toast.id)}
				/>
			{/each}
		</div>
	</div>
{:else}
	<h1 class="sr-only">Table</h1>
	<div class="pretable-page">
		<div class="pretable-panel">
			<div class="pretable-room">
				<span>Table</span>
				<span class="pretable-code">{roomId}</span>
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
				{@render seatRing(null)}
				<h2>Take a seat</h2>
				<p>Join an open seat to sit down at this table.</p>
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
				<button
					type="button"
					class="pretable-cta"
					onclick={() => liveStore?.socket.join(undefined, displayName.trim() || undefined)}
				>
					Sit down
				</button>
			{:else}
				{@render seatRing(effectiveSeat as Seat)}
				<h2>You're seated as {WIND_LABEL[seatWind(effectiveSeat as Seat)]}</h2>
				<p>
					Waiting for the rest of the table to join. The hand starts automatically once all four
					seats are ready.
				</p>
			{/if}
		</div>
	</div>
	<div class="toast-stack">
		{#each toastQueue as toast (toast.id)}
			<Toast
				message={toast.message}
				durationMs={toast.durationMs}
				onDismiss={() => dismissToast(toast.id)}
			/>
		{/each}
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
	// centered-panel chrome as the lobby's own `.panel` (routes/lobby/+page.svelte), not a new
	// visual language: panel-elevated, --color-surface, the same button/code-pill vocabulary.
	.pretable-page {
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

	.pretable-room {
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
	// to sit at rather than inventing a second layout language for the waiting room.
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
		// "waiting, alive" -- not stalled. Honest about what it doesn't know: this pulses
		// identically whether or not that seat actually has anyone in it (server/app/room.py's
		// `_seat_status_tuple` can't tell us -- an unbound seat reads the same as a connected
		// one), so it never claims occupancy, only that the table is open and listening.
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// the one seat this screen actually knows something real about: dealer is fixed at room
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

	.room-label {
		margin: 0;
		align-self: center;
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

	.turn-badge {
		color: var(--color-accent);
		font-size: var(--font-size-sm);
		text-transform: uppercase;
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

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 1fr));
		gap: 2px;
		max-width: 14rem;
	}

	.discard-pool--self {
		max-width: 20rem;
	}

	.discard-tile {
		height: clamp(22px, 3.5vw, 32px);
	}

	.discard-tile :global(.tile-face) {
		height: 100%;
	}

	.center-info {
		grid-area: center;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		text-align: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.center-info strong {
		color: var(--color-text);
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

	// hugs whatever dialog content it wraps (ScoreSheet/Chat/Settings/hand-end result) so the
	// CloseButton it contains is positioned against that panel's own corner, not the fullscreen
	// scrim's.
	.panel {
		position: relative;
	}

	.toast-stack {
		position: fixed;
		top: var(--space-4);
		right: var(--space-4);
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		max-width: 20rem;
		z-index: var(--z-overlay);
	}

	// --- Live animation demo (docs/03-frontend.md §2: transform/opacity only, no JS ticker) ---

	.animation-demo {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 32rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	.demo-hint {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.demo-actions {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.demo-actions button,
	.demo-reset {
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.demo-hand-tile {
		padding: 0;
		border: none;
		background: none;
		cursor: pointer;

		&:disabled {
			cursor: not-allowed;
		}
	}

	// the departing slot/tile: transform+opacity only, per §2 -- no layout-affecting property
	// animates, so this never triggers reflow on the ~150-element hand/pool it sits inside.
	.demo-tile-leaving {
		transition:
			transform 260ms ease-in,
			opacity 260ms ease-in;
		transform: translateY(24px) scale(0.85);
		opacity: 0;
	}

	// a claimed/kong meld is a freshly-inserted DOM node, so this animation plays automatically
	// on insert with no JS trigger needed at all.
	.demo-meld-entering {
		animation: demo-meld-in 220ms ease-out;
	}

	@keyframes demo-meld-in {
		from {
			opacity: 0;
			transform: translateY(-10px) scale(0.9);
		}
		to {
			opacity: 1;
			transform: none;
		}
	}

	// reduced motion: skip the visible motion but keep a near-instant transition running --
	// `ontransitionend` is what commits the data change (see the script section above), so
	// `transition: none` here would leave the demo permanently stuck mid-flight instead of
	// just snapping instead of sliding.
	@media (prefers-reduced-motion: reduce) {
		.demo-tile-leaving {
			transition-duration: 1ms;
			transform: none;
		}

		.demo-meld-entering {
			animation-duration: 1ms;
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

		.backs-row .mini-tile {
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
