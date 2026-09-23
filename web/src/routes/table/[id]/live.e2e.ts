import { test, expect, chromium } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// UI-level live-backend smoke test: a real `uv run uvicorn` and a real SvelteKit dev server
// (its own scratch instance, not the shared one `playwright.config.ts`'s `webServer` starts
// for the rest of this project's e2e suite -- that one has no backend behind it, and this
// needs `PUBLIC_WS_URL` pointed at a real one), driving `/table/[id]` through real browser
// contexts. `src/lib/net/live-backend.integration.spec.ts` already covers the socket+reducer
// layer against a real backend; this covers the layer that one doesn't -- the actual route UI
// this sub-task built (join/waiting screen, discard-by-click, claim buttons, declare actions)
// -- end to end.
//
// Skipped by default (spins up two extra real processes, same posture as the vitest sibling).
// Opt in explicitly:
//
//   RUN_LIVE_BACKEND_TESTS=1 pnpm exec playwright test src/routes/table/[id]/live.e2e.ts
test.skip(!process.env.RUN_LIVE_BACKEND_TESTS, 'opt-in: RUN_LIVE_BACKEND_TESTS=1');

const BACKEND_PORT = 8197;
const FRONTEND_PORT = 5197;
const BASE = `http://127.0.0.1:${FRONTEND_PORT}`;
const WEB_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../../..');
const SERVER_DIR = path.resolve(WEB_DIR, '../server');

let backend: ChildProcess | null = null;
let frontend: ChildProcess | null = null;

async function waitForHealthy(url: string, timeoutMs: number): Promise<void> {
	const deadline = Date.now() + timeoutMs;
	let lastError: unknown;
	while (Date.now() < deadline) {
		try {
			const res = await fetch(url);
			if (res.ok) return;
		} catch (err) {
			lastError = err;
		}
		await new Promise((resolve) => setTimeout(resolve, 250));
	}
	throw new Error(`${url} never became healthy: ${String(lastError)}`);
}

test.beforeAll(async () => {
	test.setTimeout(60_000); // starting two real processes is slower than the default 30s budget
	// `detached: true` + killing the whole process group on teardown, same reasoning as
	// live-backend.integration.spec.ts (uv/uvicorn forks helpers) and screenshot-pages.mjs
	// (`pnpm exec vite` doesn't forward SIGTERM to the vite process it wraps).
	backend = spawn(
		'uv',
		['run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(BACKEND_PORT)],
		{ cwd: SERVER_DIR, stdio: 'pipe', detached: true }
	);
	frontend = spawn(
		'pnpm',
		['exec', 'vite', 'dev', '--port', String(FRONTEND_PORT), '--strictPort'],
		{
			cwd: WEB_DIR,
			stdio: 'pipe',
			detached: true,
			env: { ...process.env, PUBLIC_WS_URL: `ws://127.0.0.1:${BACKEND_PORT}/ws` }
		}
	);
	await Promise.all([
		waitForHealthy(`http://127.0.0.1:${BACKEND_PORT}/healthz`, 20_000),
		waitForHealthy(BASE, 20_000)
	]);
});

test.afterAll(async () => {
	for (const proc of [backend, frontend]) {
		if (!proc || proc.pid === undefined) continue;
		const exited = new Promise<void>((resolve) => proc.once('exit', () => resolve()));
		try {
			process.kill(-proc.pid, 'SIGTERM');
		} catch {
			/* group already gone */
		}
		await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5000))]);
		try {
			process.kill(-proc.pid, 'SIGKILL');
		} catch {
			/* already gone -- the common, successful case */
		}
	}
});

test('four real seats join, ready, and play real discards/claims through the live table UI', async () => {
	test.setTimeout(60_000);
	const table = `e2e-live-${Date.now()}`;
	const browser = await chromium.launch();
	try {
		const pages = await Promise.all(
			Array.from({ length: 4 }, async () => {
				const ctx = await browser.newContext();
				return ctx.newPage();
			})
		);

		await Promise.all(
			pages.map((p) => p.goto(`${BASE}/table/${table}`, { waitUntil: 'networkidle' }))
		);
		// real guest display names (M5, docs/02-protocol.md's Auth section) -- one per seat, typed
		// into the pre-game name field before sitting down, so the assertions below can tell "this
		// text is a real server-resolved name" apart from a placeholder.
		const names = ['Alice', 'Bob', 'Carol', 'Dave'];
		for (const [i, p] of pages.entries()) {
			await p.locator('#display-name-input').fill(names[i]);
		}
		// join seats one at a time (not Promise.all) so the first joiner's own waiting-for-players
		// screen -- there's no signal from `state_sync` alone that distinguishes it from "already
		// playing" (docs/03-frontend.md §6 sub-task's own finding), so this is the one point that
		// actually exercises it -- has a real moment to render before the last `ready` starts the
		// hand and every client moves on together.
		await pages[0].getByRole('button', { name: 'Open' }).first().click();
		await expect(pages[0].getByText(/You're seated as/)).toBeVisible();
		for (const p of pages.slice(1)) {
			await expect(p.getByRole('button', { name: 'Open' }).first()).toBeVisible();
			await p.getByRole('button', { name: 'Open' }).first().click();
		}

		await Promise.all(
			pages.map((p) => p.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 20_000 }))
		);

		// every seat's real chosen name (not a "Seat N"/"You" placeholder) reaches every client --
		// state_sync.names on the snapshot each of the other three joiners already had, and
		// seat_state.name live for whoever joined after them (docs/02-protocol.md §3, this
		// sub-task's reducer wiring). Own seat: the `.seat-region--self` header. Others: anywhere
		// on the table scene, since seat-to-position varies per viewer.
		await expect(pages[0].locator('.seat-region--self .seat-name')).toHaveText(names[0]);
		for (const [i, p] of pages.entries()) {
			for (const [j, name] of names.entries()) {
				if (i === j) continue;
				// `.seat-name` only -- `getByText` alone also matches the center-info "Dealer"/"Turn"
				// strongs, which repeat whichever name is currently dealer/acting.
				await expect(p.locator('.seat-name', { hasText: name })).toBeVisible();
			}
		}

		// drive real turns until at least 3 real discards have landed somewhere, passing any
		// claim window that opens along the way -- proves discard, claim/pass, and the
		// cross-client state_sync/turn broadcast all actually work, not just that the page loaded.
		let discards = 0;
		for (let round = 0; round < 20 && discards < 3; round++) {
			let acted = false;
			for (const p of pages) {
				const pass = p.locator('.claim-btn--pass');
				if (await pass.count()) {
					await pass.click();
					acted = true;
					break;
				}
			}
			if (!acted) {
				for (const p of pages) {
					const btn = p.locator('.hand-tile-btn').first();
					if (await btn.count()) {
						await btn.click();
						discards++;
						acted = true;
						break;
					}
				}
			}
			if (acted) await pages[0].waitForTimeout(400);
			else await pages[0].waitForTimeout(800);
		}

		expect(discards).toBeGreaterThanOrEqual(3);

		// every seat's own discard pool total across all four clients should agree once settled --
		// a real cross-client broadcast, not each client's own local echo.
		await pages[0].waitForTimeout(500);
		const poolCounts = await Promise.all(
			pages.map((p) => p.locator('.discard-pool .discard-tile').count())
		);
		for (const count of poolCounts) expect(count).toBe(poolCounts[0]);
		expect(poolCounts[0]).toBeGreaterThanOrEqual(3);
	} finally {
		await browser.close();
	}
});

test('practice mode is reachable from the lobby and reaches real gameplay with bot seats marked', async () => {
	// M4.5 (docs/05-roadmap.md): the lobby's "Practice vs Bots" button generates its own table id and
	// tags the table route `?practice=1`, which `/table/[id]` translates into `&practice=true` on
	// the real WS URL -- server-side, that binds seats 1-3 to real `FaanBot`s at table creation
	// (server/app/ws.py's `ws_endpoint`/`app/table.py`'s `Table.__init__(practice=...)`), before
	// this test's one human seat ever joins. Proves the whole chain end to end: lobby button ->
	// route -> practice WS param -> bot-filled table -> the seats actually render the `bot` badge
	// this sub-task added to the table scene.
	test.setTimeout(60_000);
	const browser = await chromium.launch();
	try {
		const page = await browser.newPage();
		await page.goto(BASE, { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'Practice vs Bots' }).click();

		await expect(page).toHaveURL(/\/table\/[A-Z0-9]+\?practice=1$/);

		// a practice table's three bot seats are already bound and auto-ready the instant the
		// table exists (docs/05-roadmap.md M4.5) -- the human's own `join`/`ready` is the only real
		// gate left. Observed running against a real backend: this clears the "waiting for the
		// rest of the table" screen so fast (the table's own `ready` gate opens the instant this
		// seat's `ready` lands) that the intermediate "You're seated as" text often never renders
		// at all before `tableReady` flips -- so this only asserts the eventual, stable state
		// (the table scene itself), not the transient one in between.
		await page.getByRole('button', { name: 'Open' }).click();
		await page.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 15_000 });

		// three opponent seats, all bot-controlled -- the visual treatment this sub-task added.
		await expect(page.locator('.bot-badge')).toHaveCount(3);
		await expect(page.locator('.table-label')).toContainText('practice vs bots');

		// each bot seat's real server-assigned name (M5's `names` array) renders alongside the
		// badge, not in place of it -- both are real DOM text in the same seat-meta header. Each
		// bot draws its own random pun name (`app/table.py`'s `_draw_bot_name`), so this only
		// asserts non-empty and distinct, not a fixed literal.
		const botSeatNames = page.locator('.seat-meta:has(.bot-badge) .seat-name');
		await expect(botSeatNames).toHaveCount(3);
		const names = await botSeatNames.allTextContents();
		for (const name of names) {
			expect(name.trim().length).toBeGreaterThan(0);
		}
		expect(new Set(names).size).toBe(3);

		// hand 1's dealer is fixed at table construction and can be this human seat -- unlike the
		// four-real-seats test above, there's only one human here, so nothing discards on this
		// seat's own behalf until it's actually clicked. Tsumogiri whichever discard is offered
		// and pass any claim window, same policy as `server/tests/test_practice_mode_e2e.py`'s
		// `_play_practice_game` -- this is what actually lets the three real bots' own turns run
		// in between, proving `_poke_bots()` drives them, not just that the human's own clicks
		// produced discards.
		let sawOpponentDiscard = false;
		for (let round = 0; round < 30 && !sawOpponentDiscard; round++) {
			const pass = page.locator('.claim-btn--pass');
			if (await pass.count()) {
				await pass.click();
			} else {
				const btn = page.locator('.hand-tile-btn').first();
				if (await btn.count()) await btn.click();
			}
			await page.waitForTimeout(400);
			// any discard tile outside "Your discards" is a real bot-produced discard.
			const opponentDiscards = await page
				.locator('.discard-pool:not(.discard-pool--self) .discard-tile')
				.count();
			if (opponentDiscards > 0) sawOpponentDiscard = true;
		}
		expect(sawOpponentDiscard).toBe(true);
	} finally {
		await browser.close();
	}
});

test('completing more than one real hand accumulates multi-hand history in the ScoreSheet', async () => {
	// HK ruleset has no dead wall (mahjong_core/config.py's `wall_reserve = 0`) -- absent an
	// earlier win, a hand runs until the wall is drawn dry, ~80-something real discards. Two
	// hands plus the occasional claim window is a few hundred real round trips against the real
	// backend (observed ~70s end to end during development), hence the generous budget (this is
	// the actual proof the multi-hand lib/game/state.ts `handHistory` accumulation works end to
	// end -- docs/03-frontend.md's `/table/[id]` wiring section -- not just reducer.spec.ts's
	// hand-constructed fixtures).
	test.setTimeout(300_000);
	const table = `e2e-history-${Date.now()}`;
	const browser = await chromium.launch();
	try {
		const pages = await Promise.all(
			Array.from({ length: 4 }, async () => {
				const ctx = await browser.newContext();
				return ctx.newPage();
			})
		);

		await Promise.all(
			pages.map((p) => p.goto(`${BASE}/table/${table}`, { waitUntil: 'networkidle' }))
		);
		await pages[0].getByRole('button', { name: 'Open' }).first().click();
		for (const p of pages.slice(1)) {
			await expect(p.getByRole('button', { name: 'Open' }).first()).toBeVisible();
			await p.getByRole('button', { name: 'Open' }).first().click();
		}
		await Promise.all(
			pages.map((p) => p.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 20_000 }))
		);

		// `.panel-overlay` (the Score sheet panel's own container) is a real `position: fixed;
		// inset: 0` modal backdrop -- correctly, it intercepts pointer events for whatever's
		// behind it. Opening the Score sheet on page 0 *before* playing would permanently block
		// page 0's own hand-tile clicks for the rest of this loop, since page 0 is seat 0, a real
		// player (found by running this against a real backend: an earlier version of this test
		// opened it up front and every discard on page 0 timed out waiting for the tile to become
		// clickable). So: play the whole thing first, open the Score sheet only once play is
		// done and nothing needs to click through it anymore.
		//
		// Progress signal: `lib/net/reducer.ts`'s `deal` case is the only thing that sets
		// `wallRemaining` -- `draw` doesn't touch it -- so the "Wall" figure shown in the table
		// status region is constant for an entire hand and only ever changes at the next hand's
		// `deal`. Reading that one number is a much cheaper hand-boundary signal than repeatedly
		// opening/closing the Score sheet (or counting individual discards) would be.
		const wallCount = pages[0].locator('.wall-count strong');
		let prevWall: string | null = null;
		let handBoundaries = 0;

		// tsumogiri whichever seat is offered a real discard, auto-pass every real claim window,
		// across all four seats, until two real hand boundaries have actually landed -- bounded by
		// real wall exhaustion (or an incidental real win, which ends a hand faster), not by an
		// arbitrary action count standing in for game logic. Every page's own actionable-element
		// check runs in parallel (Promise.all) rather than one page at a time -- with 4 real
		// browser contexts, a sequential per-page round trip is the dominant cost of each round.
		for (let round = 0; round < 3000 && handBoundaries < 2; round++) {
			const wall = await wallCount.textContent().catch(() => null);
			if (prevWall !== null && wall !== null && wall !== prevWall) handBoundaries++;
			prevWall = wall;

			// the server closes claim windows early (docs/03-frontend.md §5: "buttons are up" is
			// not a stable client state) -- a pass button counted a moment ago can be gone, or
			// mid-CSS-transition and briefly "not stable" by Playwright's own actionability
			// check, by the time the click actually lands. Found by running this against a real
			// backend: retrying only page index 0 on failure produced a real deadlock -- if
			// page 0's specific click kept failing, page 1's identical, perfectly clickable pass
			// button was never even attempted, so a window with two eligible seats could sit open
			// indefinitely. Trying every matching page, not just the first, is the fix; a short
			// per-click timeout + swallow is correct either way since the next round's fresh poll
			// is the real recovery path.
			// hand-end hold (docs/00-architecture.md §3): every hand end -- win or exhaustive
			// draw -- holds the round open for up to the real `ruleset.hand_end_seconds` (10s)
			// unless every seat acks first. Without dismissing here, each of this loop's two hand
			// boundaries would pay that real 10s wait instead of advancing as soon as all four
			// pages click through -- multiplied by however many hands actually land during this
			// loop, that's the difference between this test finishing in seconds vs. minutes.
			const overlayCounts = await Promise.all(
				pages.map((p) => p.getByTestId('faan-overlay').count())
			);
			for (let i = 0; i < pages.length; i++) {
				if (overlayCounts[i] <= 0) continue;
				await pages[i]
					.getByTestId('faan-overlay')
					.getByRole('button', { name: 'Close' })
					.click({ timeout: 800 })
					.catch(() => {});
			}

			let progressed = false;
			const passCounts = await Promise.all(pages.map((p) => p.locator('.claim-btn--pass').count()));
			for (let i = 0; i < pages.length && !progressed; i++) {
				if (passCounts[i] <= 0) continue;
				progressed = await pages[i]
					.locator('.claim-btn--pass')
					.click({ timeout: 800 })
					.then(() => true)
					.catch(() => false);
			}
			if (progressed) continue;

			const discardCounts = await Promise.all(
				pages.map((p) => p.locator('.hand-tile-btn').count())
			);
			for (let i = 0; i < pages.length && !progressed; i++) {
				if (discardCounts[i] <= 0) continue;
				progressed = await pages[i]
					.locator('.hand-tile-btn')
					.first()
					.click({ timeout: 800 })
					.then(() => true)
					.catch(() => false);
			}
			if (progressed) continue;

			// nobody has a real action offered right now (mid-broadcast, or a claim window still
			// resolving) -- a short beat for the next server event, not a fixed per-action cost.
			await pages[0].waitForTimeout(100);
		}

		expect(handBoundaries).toBeGreaterThanOrEqual(2);

		await pages[0].getByRole('button', { name: 'Score sheet' }).click();
		const handRows = pages[0].locator('.score-sheet tbody tr');
		await expect(handRows).toHaveCount(2, { timeout: 10_000 });
		await expect(handRows.nth(0).locator('td').first()).toHaveText('1');
		await expect(handRows.nth(1).locator('td').first()).toHaveText('2');
	} finally {
		await browser.close();
	}
});

test('a real game reaching game_end auto-shows the game-end summary, and a past round reveals its real winning hand', async () => {
	// Real `game_end` (docs/03-frontend.md §6's "Game-end summary") only fires once EAST_ONLY's
	// minimum 4 hands have played out (mahjong_core/engine.py's `start_next_hand`, dealer
	// 0->1->2->3 wrapping back to 0) -- practice mode (one human seat, three real `FaanBot`
	// seats) so only this seat's own turns need driving through Playwright; the bots run via the
	// server's own `_poke_bots()` with no browser round trip at all, the same speed advantage
	// `live.e2e.ts`'s "practice mode is reachable..." test above already relies on. `no_calls`/
	// `auto_pass_chow` pre-armed so this seat's own claim windows never need a click either
	// (server/app/table.py's `set_auto` -- persists on the seat binding for the life of the
	// table, not just "this hand" despite the toggle's own label). Dealer repeats on a win or
	// draw (`ruleset.dealer_repeat_on_win`/`dealer_repeat_on_draw`, both default `True`) mean
	// this can run more than the 4-hand minimum -- bounded by a generous wall-clock budget, not
	// a fixed hand count. Observed running against a real backend: a single no-dead-wall HK hand
	// (wall_reserve=0, up to ~34 draws/seat) with zero repeats already takes several minutes
	// end to end, so the budget below assumes at least one repeat on top of the 4-hand minimum.
	test.setTimeout(1_800_000);
	const browser = await chromium.launch();
	try {
		const page = await browser.newPage();
		await page.goto(BASE, { waitUntil: 'networkidle' });
		await page.getByRole('button', { name: 'Practice vs Bots' }).click();
		await page.getByRole('button', { name: 'Open' }).click();
		await page.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 15_000 });

		await page.getByRole('button', { name: 'Settings' }).click();
		await page.getByLabel('No calls this hand').check();
		await page.getByLabel('Auto-pass chow').check();
		await page.getByRole('button', { name: 'Close' }).click();

		const gameEndOverlay = page.getByTestId('game-end-overlay');
		const deadline = Date.now() + 1_770_000;
		while (Date.now() < deadline) {
			if (await gameEndOverlay.count()) break;

			const faanOverlay = page.getByTestId('faan-overlay');
			if (await faanOverlay.count()) {
				await faanOverlay
					.getByRole('button', { name: 'Close' })
					.click({ timeout: 800 })
					.catch(() => {});
				continue;
			}

			const pass = page.locator('.claim-btn--pass');
			if (await pass.count()) {
				await pass.click({ timeout: 800 }).catch(() => {});
				continue;
			}

			const discard = page.locator('.hand-tile-btn').first();
			if (await discard.count()) {
				await discard.click({ timeout: 800 }).catch(() => {});
				continue;
			}

			await page.waitForTimeout(150);
		}

		await expect(gameEndOverlay).toBeVisible({ timeout: 5_000 });
		await expect(gameEndOverlay.getByRole('heading', { name: 'Game over' })).toBeVisible();
		await expect(gameEndOverlay.locator('.standings li')).toHaveCount(4);

		// past-round detail: this is the actual gap the melds-snapshotting sub-task closed
		// (`HandHistoryEntry.winnerMelds`, lib/game/state.ts) -- expand hand 1's row and confirm
		// it shows either a real winning hand (melds/concealed tiles rendered via TileFace) or
		// the plain exhaustive-draw note, not blank/broken output for data that's since scrolled
		// out of `state.melds`.
		const round1Row = gameEndOverlay.locator('.score-sheet tbody tr').first();
		const round1Toggle = round1Row.locator('.round-expand');
		await round1Toggle.click();
		const detail1 = gameEndOverlay.locator('#round-detail-1');
		await expect(detail1).toBeVisible();
		const hasWinner = (await detail1.getByRole('heading', { name: /wins$/ }).count()) > 0;
		if (hasWinner) {
			await expect(detail1.locator('.tile')).not.toHaveCount(0);
		} else {
			await expect(detail1).toContainText('Exhaustive draw');
		}
	} finally {
		await browser.close();
	}
});
