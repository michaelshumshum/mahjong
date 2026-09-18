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
	const room = `e2e-live-${Date.now()}`;
	const browser = await chromium.launch();
	try {
		const pages = await Promise.all(
			Array.from({ length: 4 }, async () => {
				const ctx = await browser.newContext();
				return ctx.newPage();
			})
		);

		await Promise.all(
			pages.map((p) => p.goto(`${BASE}/table/${room}`, { waitUntil: 'networkidle' }))
		);
		// join seats one at a time (not Promise.all) so the first joiner's own waiting-for-players
		// screen -- there's no signal from `state_sync` alone that distinguishes it from "already
		// playing" (docs/03-frontend.md §6 sub-task's own finding), so this is the one point that
		// actually exercises it -- has a real moment to render before the last `ready` starts the
		// hand and every client moves on together.
		await pages[0].getByRole('button', { name: 'Sit down' }).click();
		await expect(pages[0].getByText(/You're seated as/)).toBeVisible();
		for (const p of pages.slice(1)) {
			await expect(p.getByRole('button', { name: 'Sit down' })).toBeVisible();
			await p.getByRole('button', { name: 'Sit down' }).click();
		}

		await Promise.all(
			pages.map((p) => p.getByTestId('table-scene').waitFor({ state: 'visible', timeout: 20_000 }))
		);

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

test('completing more than one real hand accumulates multi-hand history in the ScoreSheet', async () => {
	// HK ruleset has no dead wall (mahjong_core/config.py's `wall_reserve = 0`) -- absent an
	// earlier win, a hand runs until the wall is drawn dry, ~80-something real discards. Two
	// hands plus the occasional claim window is a few hundred real round trips against the real
	// backend (observed ~70s end to end during development), hence the generous budget (this is
	// the actual proof the multi-hand lib/game/state.ts `handHistory` accumulation works end to
	// end -- docs/03-frontend.md's `/table/[id]` wiring section -- not just reducer.spec.ts's
	// hand-constructed fixtures).
	test.setTimeout(300_000);
	const room = `e2e-history-${Date.now()}`;
	const browser = await chromium.launch();
	try {
		const pages = await Promise.all(
			Array.from({ length: 4 }, async () => {
				const ctx = await browser.newContext();
				return ctx.newPage();
			})
		);

		await Promise.all(
			pages.map((p) => p.goto(`${BASE}/table/${room}`, { waitUntil: 'networkidle' }))
		);
		await pages[0].getByRole('button', { name: 'Sit down' }).click();
		for (const p of pages.slice(1)) {
			await expect(p.getByRole('button', { name: 'Sit down' })).toBeVisible();
			await p.getByRole('button', { name: 'Sit down' }).click();
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
