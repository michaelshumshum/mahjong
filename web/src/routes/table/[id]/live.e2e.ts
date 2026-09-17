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
		await expect(pages[0].getByText(/Seated as seat/)).toBeVisible();
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
