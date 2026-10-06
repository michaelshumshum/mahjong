import { test, expect, chromium } from '@playwright/test';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

// UI-level live-backend smoke test (real uvicorn + dev server) driving /table/[id] end to end;
// live-backend.integration.spec.ts covers socket+reducer. Skipped by default: RUN_LIVE_BACKEND_TESTS=1.
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
	test.setTimeout(60_000); // two real processes are slower than the default 30s budget
	// detached:true + kill the process group on teardown -- vite doesn't forward SIGTERM; uvicorn forks helpers.
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
		// one real guest display name per seat, typed before sitting down, so the assertions
		// below can tell a real server-resolved name apart from a placeholder.
		const names = ['Alice', 'Bob', 'Carol', 'Dave'];
		for (const [i, p] of pages.entries()) {
			await p.locator('#display-name-input').fill(names[i]);
		}
		// join seats one at a time (not Promise.all) so the first joiner's waiting-for-players
		// screen has a real moment to render before the last `ready` starts the hand.
		await pages[0].locator('.seat-ring-slot--open').first().click();
		await expect(pages[0].getByText(/You're seated as/)).toBeVisible();
		for (const p of pages.slice(1)) {
			await expect(p.locator('.seat-ring-slot--open').first()).toBeVisible();
			await p.locator('.seat-ring-slot--open').first().click();
		}

		await Promise.all(
			pages.map((p) => p.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 20_000 }))
		);

		// every seat's real chosen name reaches every client. Own seat: the .seat-region--self
		// header. Others: anywhere on the scene, since seat-to-position varies per viewer.
		await expect(pages[0].locator('.seat-region--self .seat-name')).toHaveText(names[0]);
		for (const [i, p] of pages.entries()) {
			for (const [j, name] of names.entries()) {
				if (i === j) continue;
				// `.seat-name` only -- `getByText` alone also matches the center-info Dealer/Turn text.
				await expect(p.locator('.seat-name', { hasText: name })).toBeVisible();
			}
		}

		// drive real turns until at least 3 discards have landed, passing any claim window along
		// the way -- proves discard, claim/pass, and cross-client broadcast all actually work.
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
						// the acting seat's own tab title flips to the your-turn state (P1.12).
						await expect(p).toHaveTitle('Your turn · Mahjong');
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
	// "Practice vs Bots" tags the table `?practice=1`, which /table/[id] turns into `&practice=true`
	// on the WS URL, binding seats 1-3 to real bots at creation -- proves lobby button -> bot table -> badge.
	test.setTimeout(60_000);
	const browser = await chromium.launch();
	try {
		const page = await browser.newPage();
		await page.goto(BASE, { waitUntil: 'networkidle' });
		await page.getByTestId('lobby-practice-bots').click();

		await expect(page).toHaveURL(/\/table\/[A-Z0-9]+\?practice=1$/);

		// bot seats are already bound and auto-ready, so the waiting screen clears so fast the
		// intermediate "You're seated as" text often never renders -- assert the stable end state.
		await page.locator('.seat-ring-slot--open').click();
		await page.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 15_000 });

		// three opponent seats, all bot-controlled.
		await expect(page.locator('.bot-badge')).toHaveCount(3);
		await expect(page.locator('.table-label')).toContainText('practice vs bots');

		// each bot's server-assigned name renders alongside the badge, not in place of it. Each
		// draws its own random pun name, so this only asserts non-empty and distinct.
		const botSeatNames = page.locator('.seat-meta:has(.bot-badge) .seat-name');
		await expect(botSeatNames).toHaveCount(3);
		const names = await botSeatNames.allTextContents();
		for (const name of names) {
			expect(name.trim().length).toBeGreaterThan(0);
		}
		expect(new Set(names).size).toBe(3);

		// tsumogiri whichever discard is offered and pass any claim window -- this lets the three
		// bots' own turns run in between, proving the server drives them, not just the human's clicks.
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
			// any discard tile outside "Your discards" is a bot-produced discard.
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
	// HK ruleset has no dead wall (`wall_reserve = 0`) -- absent an earlier win, a hand runs until
	// the wall's dry (~80 discards); two hands is hundreds of round trips, hence the generous budget.
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
		await pages[0].locator('.seat-ring-slot--open').first().click();
		for (const p of pages.slice(1)) {
			await expect(p.locator('.seat-ring-slot--open').first()).toBeVisible();
			await p.locator('.seat-ring-slot--open').first().click();
		}
		await Promise.all(
			pages.map((p) => p.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 20_000 }))
		);

		// `.panel-overlay` blocks pointer events, so opening Score sheet before playing would block
		// seat 0's hand-tile clicks. Progress signal: only `deal` sets wallRemaining, once per hand.
		const wallCount = pages[0].locator('.wall-count strong');
		let prevWall: string | null = null;
		let handBoundaries = 0;

		// tsumogiri whichever seat is offered a discard, auto-pass every claim window, until two
		// hand boundaries land (bounded by wall exhaustion). Every page's check runs in parallel.
		for (let round = 0; round < 3000 && handBoundaries < 2; round++) {
			const wall = await wallCount.textContent().catch(() => null);
			if (prevWall !== null && wall !== null && wall !== prevWall) handBoundaries++;
			prevWall = wall;

			// claim windows close early, so a counted pass button may vanish before the click lands;
			// retrying only page 0 deadlocked, so try every page. Dismissing hand-end here skips the full wait.
			const overlayCounts = await Promise.all(
				pages.map((p) => p.getByTestId('faan-overlay').count())
			);
			for (let i = 0; i < pages.length; i++) {
				if (overlayCounts[i] <= 0) continue;
				await pages[i]
					.getByTestId('faan-overlay')
					.getByTestId('close-button')
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

			// nobody has an action offered right now -- a short beat for the next server event.
			await pages[0].waitForTimeout(100);
		}

		expect(handBoundaries).toBeGreaterThanOrEqual(2);

		await pages[0].getByTestId('toggle-score-sheet').click();
		const handRows = pages[0].locator('.score-sheet tbody tr');
		await expect(handRows).toHaveCount(2, { timeout: 10_000 });
		await expect(handRows.nth(0).locator('td').first()).toHaveText('1');
		await expect(handRows.nth(1).locator('td').first()).toHaveText('2');
	} finally {
		await browser.close();
	}
});

test('a real game reaching game_end auto-shows the game-end summary, and a past round reveals its real winning hand', async () => {
	// `game_end` needs EAST_ONLY's min 4 hands; practice mode + pre-armed no_calls/auto_pass_chow
	// means only this seat needs driving. Dealer repeats can run past 4 hands, hence the generous timeout.
	test.setTimeout(1_800_000);
	const browser = await chromium.launch();
	try {
		const page = await browser.newPage();
		await page.goto(BASE, { waitUntil: 'networkidle' });
		await page.getByTestId('lobby-practice-bots').click();
		await page.locator('.seat-ring-slot--open').click();
		await page.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 15_000 });

		await page.getByTestId('toggle-settings').click();
		await page.getByLabel('No calls this hand').check();
		await page.getByLabel('Auto-pass chow').check();
		await page.getByTestId('close-button').click();

		const gameEndOverlay = page.getByTestId('game-end-overlay');
		const deadline = Date.now() + 1_770_000;
		while (Date.now() < deadline) {
			if (await gameEndOverlay.count()) break;

			const faanOverlay = page.getByTestId('faan-overlay');
			if (await faanOverlay.count()) {
				await faanOverlay
					.getByTestId('close-button')
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

		// past-round detail: expand hand 1's row and confirm a real winning hand or exhaustive-draw
		// note renders, not blank/broken output for data long since scrolled out of `state.melds`.
		const round1Row = gameEndOverlay.locator('.score-sheet tbody tr').first();
		const round1Toggle = round1Row.locator('.round-expand');
		await round1Toggle.click();
		const detail1 = gameEndOverlay.locator('#round-detail-1');
		await expect(detail1).toBeVisible();
		const isDraw = (await detail1.textContent())?.includes('Exhaustive draw') ?? false;
		if (isDraw) {
			await expect(detail1).toContainText('Exhaustive draw');
		} else {
			await expect(detail1).toContainText('Total');
			await expect(detail1.locator('.tile')).not.toHaveCount(0);
		}
	} finally {
		await browser.close();
	}
});
