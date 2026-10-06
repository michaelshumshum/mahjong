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
	import { applyMotionPref } from '$lib/ui/motion';
	import {
		clearSeatForTable,
		clearSecretForTable,
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
	import OpponentRegion from '$lib/table/OpponentRegion.svelte';
	import CenterDiscardPool from '$lib/table/CenterDiscardPool.svelte';
	import YourSeatRegion from '$lib/table/YourSeatRegion.svelte';
	import HandEndOverlay from './_components/HandEndOverlay.svelte';
	import DismissablePanel from '$lib/ui/DismissablePanel.svelte';
	import TableToolbar from './_components/TableToolbar.svelte';
	import MockTableToolbar from './_components/MockTableToolbar.svelte';
	import PretableScreen from './_components/PretableScreen.svelte';
	import LeaveGameDialog from './_components/LeaveGameDialog.svelte';
	import { m } from '$lib/paraglide/messages.js';

	// `?mock=<scenarioId>` renders a frozen MOCK_SCENARIOS fixture with no backend (screenshot
	// workflow); omitted, `[id]` opens a real MahjongSocket -> GameStore through the same view model.
	let isMock = $derived(page.url.searchParams.has('mock'));
	let tableId = $derived(page.params.id ?? '');

	// `?practice=1` (unrelated in spelling to the wire's own `&practice=true`) opens the live
	// socket in practice mode: seats 1-3 are already bot-bound at table creation.
	let isPractice = $derived(page.url.searchParams.has('practice'));

	// `?pregame=connecting|join|waiting` freezes on one live pre-game state with no real socket --
	// a MOCK_SCENARIOS fixture (always fully-seated) has no room for these, so it's a mode of its own.
	const PREGAME_PREVIEWS = ['connecting', 'join', 'waiting'] as const;
	type PregamePreview = (typeof PREGAME_PREVIEWS)[number];
	let pregamePreview = $derived.by((): PregamePreview | null => {
		const raw = page.url.searchParams.get('pregame');
		return (PREGAME_PREVIEWS as readonly string[]).includes(raw ?? '')
			? (raw as PregamePreview)
			: null;
	});
	// arbitrary seat for the 'waiting' preview -- wind comes from whichever dealer the
	// MOCK_SCENARIOS fallback happens to carry.
	const PREGAME_PREVIEW_SEAT = 1 as Seat;

	// any value other than a known scenario id (including a bare `?mock` flag) falls back to
	// the first scenario.
	let initialMockParam = page.url.searchParams.get('mock');
	let scenarioId = $state(
		MOCK_SCENARIOS.some((s) => s.id === initialMockParam) ? initialMockParam! : MOCK_SCENARIOS[0].id
	);
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
		const practiceParam = isPractice ? '&practice=true' : '';
		// no persisted seat yet -- connect as a spectator so the seat picker shows real occupancy
		// instead of four identical "Open" slots; `join` promotes off spectator status on pick.
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
				pushToast(
					m.tablePage_actionFailedToast({
						error: event.d.error ?? m.tablePage_unknownErrorLabel()
					})
				);
			}
			// persist join's one-time reconnect credential so a later reload can present it back
			// on `hello{seat, secret}` instead of losing the seat.
			if (event.t === 'ack' && event.d.reconnect_secret != null) {
				saveSecretForTable(tableId, event.d.reconnect_secret);
			}
			if (event.t === 'error') {
				pushToast(m.tablePage_serverErrorToast({ message: event.d.message }));
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
		tiles?: TileCode[];
		onClick: () => void;
	}

	// legal_actions' own kind tags are the longer declare_*/claim_* forms; the wire declare{kind}
	// intent takes the shorter concealed_kong|added_kong|win -- two vocabularies, one concept.
	let declareOptions = $derived.by((): DeclareOption[] => {
		if (isMock || !liveStore) return [];
		const options: DeclareOption[] = [];
		for (const action of liveStore.state.legalActions) {
			const meld = action.meld as { tiles?: number[] } | undefined;
			if (action.kind === 'declare_win') {
				const store = liveStore;
				options.push({
					key: 'win',
					label: m.tablePage_declareWinLabel(),
					onClick: () => store.socket.declareWin()
				});
			} else if (action.kind === 'declare_concealed_kong' && meld?.tiles) {
				const store = liveStore;
				const tiles = meld.tiles;
				options.push({
					key: `ck-${tiles.join(',')}`,
					label: m.tablePage_declareConcealedKongLabel(),
					tiles: tiles.map(tileIdToCode),
					onClick: () => store.socket.declareConcealedKong(tiles)
				});
			} else if (action.kind === 'declare_added_kong' && meld?.tiles) {
				const store = liveStore;
				const tiles = meld.tiles;
				options.push({
					key: `ak-${tiles.join(',')}`,
					label: m.tablePage_declareAddedKongLabel(),
					tiles: tiles.map(tileIdToCode),
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

	// hand-end hold: dismissing is per-seat, tracked locally and sent once via `hand_end_ack` --
	// reset per hand, mirroring `readySent`'s one-shot pattern but keyed on `handNo`.
	let handEndAckSent = $state(false);
	$effect(() => {
		void gameState.handNo;
		handEndAckSent = false;
	});
	// mock mode and spectators have no hand_end_ack round trip to hide the overlay behind --
	// dismissing just closes it locally, reset when the scenario picker jumps or the next hand starts.
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
		// by which tile codes the option actually names.
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

	// persisted to localStorage. `autoArm` is "last known intent," not verified truth -- re-sent
	// on each fresh connection instead of read back. Display name persists the same way but is sent once on `join`.
	let displayName = $state(loadDisplayName() ?? '');
	function updateDisplayName(value: string): void {
		displayName = value;
		saveDisplayName(value);
	}

	let autoArm: AutoArm = $state(loadAutoArm() ?? { noCalls: false, autoPassChow: false });
	let clientPrefs: ClientPrefs = $state(
		loadClientPrefs() ?? { soundEnabled: true, motion: 'system' }
	);
	// guards the one-shot re-send above per live connection instance, mirroring `readySent`.
	let autoArmSent = $state(false);

	let toastQueue: ToastEntry[] = $state([]);
	function pushToast(message: string): void {
		toastQueue = [...toastQueue, createToast(message)];
	}
	function dismissToast(id: number): void {
		toastQueue = removeToast(toastQueue, id);
	}

	let showAnimationDemo = $state(false);

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

	<div class="table-page">
		{#if isMock}
			<MockTableToolbar
				bind:scenarioId
				wallCount={gameState.wallCount}
				prevailing={gameState.prevailing}
				onLeaveClick={handleLeaveClick}
				onToggleScoreSheet={() => (showScoreSheet = !showScoreSheet)}
				onToggleSettings={() => (showSettings = !showSettings)}
				onToggleAnimationDemo={() => (showAnimationDemo = !showAnimationDemo)}
			/>
		{:else}
			<TableToolbar
				{spectating}
				{tableId}
				{isPractice}
				seat={liveStore?.state.seat ?? null}
				wallCount={gameState.wallCount}
				prevailing={gameState.prevailing}
				onLeaveClick={handleLeaveClick}
				onToggleScoreSheet={() => (showScoreSheet = !showScoreSheet)}
				onToggleSettings={() => (showSettings = !showSettings)}
			/>
		{/if}

		<div class="table-wrap">
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
						ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(2).name })}
					/>
					<CenterDiscardPool
						seat={seatAt(3)}
						position="left"
						ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(3).name })}
					/>
					<CenterDiscardPool
						seat={seatAt(1)}
						position="right"
						ariaLabel={m.tablePage_discardsAriaLabel({ name: seatAt(1).name })}
					/>
					<CenterDiscardPool
						seat={seatAt(0)}
						position="self"
						ariaLabel={spectating
							? m.tablePage_discardsAriaLabel({ name: seatAt(0).name })
							: m.tablePage_yourDiscardsAriaLabel()}
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
					<p class="sr-only" data-testid="claim-choice">
						{m.tablePage_claimChoiceLabel({ kind: lastClaimChoice.kind })}
					</p>
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
			<div class="panel-overlay panel-overlay--scrollable" data-testid="game-end-overlay">
				<div class="panel panel--scrollable">
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
						applyMotionPref(next.motion);
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
	<h1 class="sr-only">{m.tablePage_heading()}</h1>
	<div class="pretable-page">
		<PretableScreen
			{tableId}
			onLeaveClick={handleLeaveClick}
			{copiedInviteLink}
			{copyInviteLinkFailed}
			onCopyInviteLink={copyInviteLink}
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
	@use '$lib/styles/buttons';

	.table-page {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
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
		flex: 1;
		min-height: 0;
	}

	.table-surface {
		@include layout.seat-region-grid;
		position: relative;
		height: 100%;
		min-height: 420px;
		padding: var(--space-3);
		overflow: hidden;
		border-radius: var(--radius-lg);
		// local override: --color-text-muted (walnut chrome) fails contrast on felt green;
		// every descendant using it (seat-wind, seat-score, …) gets the felt-safe value for free.
		--color-text-muted: var(--color-felt-muted);
		// walnut rim: a solid border plus an inner highlight ring (the lip catching light) and an
		// outer shadow (the rim sitting above the room, not flush with it).
		border: 10px solid var(--color-rim);
		box-shadow:
			inset 0 0 0 2px var(--color-rim-hi),
			0 10px 28px rgb(0 0 0 / 0.5);
		// felt: lit from above-centre, falling off to a deeper green at the rails.
		background: radial-gradient(
			ellipse 120% 85% at 50% 35%,
			var(--color-felt-lit),
			var(--color-felt) 55%,
			var(--color-felt-deep) 100%
		);
	}

	// static woven-felt grain (inline SVG feTurbulence, ~4% opacity), not a texture asset.
	// position: absolute keeps it out of the surface's own grid; pointer-events: none below it.
	.table-surface::before {
		content: '';
		position: absolute;
		inset: 0;
		pointer-events: none;
		opacity: 0.04;
		background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='180' height='180'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
		background-size: 180px 180px;
	}

	// all four discard pools live in the centre, forming a box instead of each sitting at its own
	// seat's edge. Below tablet-up there's no room for a literal box, so the pools just stack.
	.table-center {
		grid-area: center;
		display: flex;
		flex-direction: column;
		align-items: center;

		@include layout.tablet-up {
			display: grid;
			grid-template-areas:
				'.    across .'
				'left .      right'
				'.    self   .';
			grid-template-columns: clamp(26px, 4vw, 36px) 1fr clamp(26px, 4vw, 36px);
			grid-template-rows: clamp(26px, 4vw, 36px) 1fr clamp(26px, 4vw, 36px);
		}
	}

	// zone guide: a faint felt-line box around the discard area, reading as a dealt-in-the-centre
	// marking on the felt (like a real table's rail line), not a UI chrome border.
	.table-center {
		@include layout.tablet-up {
			outline: 1px solid var(--color-felt-line);
			outline-offset: var(--space-2);
			border-radius: var(--radius-sm);
		}
	}

	// centered, scrim-backed like `.panel-overlay` below -- a claim decision is as consequential as
	// a hand result, so it gets the same modal weight, not a translucent row over an interactive table.
	.claim-overlay,
	.panel-overlay {
		@include buttons.modal-scrim;
	}

	// game-end content can be tall (podium + full score sheet + standings), so let the overlay
	// itself scroll rather than clipping inside a fixed-height panel.
	.panel-overlay--scrollable {
		align-items: flex-start;
		overflow-y: auto;
	}

	// hugs whatever dialog content it wraps so CloseButton is positioned against the panel's own
	// corner, not the fullscreen scrim's.
	.panel {
		position: relative;
	}

	.panel--scrollable {
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

		.table-surface {
			flex: 1 0 auto;
			height: auto;
		}
	}
</style>
