#!/usr/bin/env node
// Regenerates docs/screenshots/*.png for the "notable pages" list below.
//
// Self-contained: starts its own dev server on a scratch port, polls until it's actually
// serving (never a raw sleep), captures every page, then stops the server it started — safe
// to run repeatedly without EADDRINUSE or leftover processes. See
// .claude/skills/frontend-screenshots/SKILL.md for the workflow this feeds into (when to run
// it, where the output goes, what to commit).
//
// Usage: node scripts/screenshot-pages.mjs   (run from web/, or via `pnpm run screenshots`)

import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const WEB_DIR = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const REPO_ROOT = path.dirname(WEB_DIR);
const OUT_DIR = path.join(REPO_ROOT, 'docs', 'screenshots');
const PORT = 5199; // scratch port, distinct from the normal dev port (5173) to avoid collisions
const BASE = `http://127.0.0.1:${PORT}`;
const DESKTOP = { width: 1400, height: 900 };
// iPhone 12-14 logical size -- the phone layout (docs/frontend.md §3) below 768px.
const PHONE = { width: 390, height: 844 };
// the same phone held sideways -- the compact short-landscape layout (docs/frontend.md §3).
const PHONE_LANDSCAPE = { width: 844, height: 390 };
// the hand-end/game-end panels stagger their entrance (tiles, then faan rows, then payments);
// capture once it has settled, not mid-reveal.
const HAND_END_REVEAL_MS = 2500;
const GAME_END_REVEAL_MS = 1200;

const LOBBY_TABLES = [
	{
		id: 'K7QM2P',
		status: 'open',
		hand_no: 1,
		seats: [
			{ status: 'connected', name: 'Alice' },
			{ status: 'empty', name: null },
			{ status: 'connected', name: 'Wing' },
			{ status: 'empty', name: null }
		]
	},
	{
		id: 'R4HX9T',
		status: 'in_progress',
		hand_no: 5,
		seats: [
			{ status: 'connected', name: 'Mei' },
			{ status: 'bot', name: 'FaanBot' },
			{ status: 'connected', name: 'Chris' },
			{ status: 'bot', name: 'FaanBot' }
		]
	}
];

// phones collapse the mock scenario buttons into a disclosure (MockTableToolbar); open it first
// so the same accessible names work at every viewport.
async function pickScenario(page, name) {
	const closed = page.locator('[data-testid="scenario-disclosure"]:not([open]) > summary');
	if (await closed.isVisible()) await closed.click();
	await page.getByRole('button', { name }).click();
}

// The "notable pages" list — keep this curated and small (this is what ends up in the
// README), not exhaustive. Add a page here when it becomes a meaningful, stable part of the
// app; don't add every mock scenario. `viewport` defaults to DESKTOP.
const PAGES = [
	{ name: 'lobby', url: '/' },
	// the ruleset picker `POST /tables` (docs/protocol.md §10) needs before a table can be
	// created -- genuinely distinct from the plain lobby buttons above.
	{
		name: 'lobby-create-dialog',
		url: '/',
		async before(page) {
			await page.getByRole('button', { name: 'Create a table' }).click();
		}
	},
	{ name: 'tables', url: '/tables' },
	// `?mock=1` is required now that `/table/[id]` defaults to opening a real WebSocket against
	// `[id]` as a table id (docs/frontend.md §7) -- there's no backend running during a
	// screenshot capture, so these opt into the frozen MOCK_SCENARIOS fixture path explicitly
	// rather than relying on it being the unauthenticated default.
	{ name: 'table-your-turn', url: '/table/demo123?mock=1' },
	{
		name: 'table-claim-window',
		url: '/table/demo123?mock=1',
		async before(page) {
			await pickScenario(page, 'Claim window open (you)');
		}
	},
	{
		name: 'table-hand-ended',
		url: '/table/demo123?mock=1',
		async before(page) {
			await pickScenario(page, 'Hand just ended');
			await page.waitForTimeout(HAND_END_REVEAL_MS);
		}
	},
	// exhaustive draw gets its own plain summary card, not FaanBreakdown (docs/architecture.md
	// §3 "Hand-end hold" -- the hold itself is uniform across outcomes, but a draw has no
	// winner/patterns/payments to show), genuinely distinct enough to warrant its own capture.
	{
		name: 'table-hand-ended-draw',
		url: '/table/demo123?mock=1',
		async before(page) {
			await pickScenario(page, 'Hand ended in a draw');
			await page.waitForTimeout(150);
		}
	},
	// Auto-shown once a real `game_end` lands (docs/frontend.md §7 "Game-end summary") --
	// genuinely distinct from `table-hand-ended` above: a full-game score summary with
	// expandable per-round detail and a link back to the lobby, not a single hand's overlay.
	// `&practice=1` so the capture shows the practice-only "Play again" action.
	{
		name: 'table-game-ended',
		url: '/table/demo123?mock=1&practice=1',
		async before(page) {
			await pickScenario(page, 'Game just ended');
			await page.waitForTimeout(GAME_END_REVEAL_MS);
		}
	},
	// Settings panel: a distinct chrome surface (pre-arm toggles, sound, motion) now styled to
	// match the score sheet's panel/cards look.
	{
		name: 'table-settings',
		url: '/table/demo123?mock=1',
		async before(page) {
			await page.getByRole('button', { name: 'Settings' }).click();
		}
	},
	// Pre-game states (docs/frontend.md's "/table/[id] wiring") only ever occur on the real
	// `liveStore`-driven path -- `?mock=` always renders a fully-seated, already-dealt table
	// (`tableReady` is unconditionally true when `isMock`), so there's no MOCK_SCENARIOS entry
	// that could stand in for "not seated yet" or "seated, waiting for others". `?pregame=
	// connecting|join|waiting` freezes on one of these three with no real socket opened at all
	// -- same "repeatable, no backend running" posture `?mock=` already gives this script,
	// chosen over spawning a real `uv run uvicorn` backend just for these three captures.
	{
		name: 'table-pregame-connecting',
		url: '/table/demo123?pregame=connecting'
	},
	{ name: 'table-pregame-join', url: '/table/demo123?pregame=join' },
	{ name: 'table-pregame-waiting', url: '/table/demo123?pregame=waiting' },
	// phone captures (portrait and landscape) are viewport-only (not fullPage): what fits on one screen is the point,
	// including the sticky hand footer.
	{ name: 'lobby-phone', url: '/', viewport: PHONE },
	{ name: 'table-your-turn-phone', url: '/table/demo123?mock=1', viewport: PHONE },
	{
		name: 'table-your-turn-phone-landscape',
		url: '/table/demo123?mock=1',
		viewport: PHONE_LANDSCAPE
	},
	{
		name: 'table-claim-window-phone',
		url: '/table/demo123?mock=1',
		viewport: PHONE,
		async before(page) {
			await pickScenario(page, 'Claim window open (you)');
		}
	},
	{
		name: 'table-hand-ended-phone',
		url: '/table/demo123?mock=1',
		viewport: PHONE,
		async before(page) {
			await pickScenario(page, 'Hand just ended');
			await page.waitForTimeout(HAND_END_REVEAL_MS);
		}
	},
	{
		name: 'table-game-ended-phone',
		url: '/table/demo123?mock=1&practice=1',
		viewport: PHONE,
		async before(page) {
			await pickScenario(page, 'Game just ended');
			await page.waitForTimeout(GAME_END_REVEAL_MS);
		}
	}
];

async function waitForServer(url, timeoutMs = 30_000) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		try {
			const res = await fetch(url);
			if (res.ok) return;
		} catch {
			// not up yet
		}
		await new Promise((r) => setTimeout(r, 300));
	}
	throw new Error(`dev server on ${url} did not become ready within ${timeoutMs}ms`);
}

async function main() {
	await mkdir(OUT_DIR, { recursive: true });

	// detached so we own the whole process group -- `pnpm exec vite` is a wrapper that doesn't
	// forward SIGTERM to the real vite process it spawns, so killing just this PID leaves vite
	// (and the event loop it holds open via its stdio pipes) running forever. Killing the group
	// (negative pid) reaches vite's actual process too.
	// `--host 127.0.0.1`, not vite's bare default: unset, vite/node's `localhost` resolution can
	// bind IPv6-only (`::1`) depending on the host's resolver order, which then refuses a plain
	// `fetch('http://localhost:...')` connect below on a system that resolves `localhost` to
	// `127.0.0.1` first -- explicit means this can't depend on that order either way.
	const server = spawn(
		'pnpm',
		['exec', 'vite', 'dev', '--host', '127.0.0.1', '--port', String(PORT), '--strictPort'],
		{
			cwd: WEB_DIR,
			stdio: ['ignore', 'pipe', 'pipe'],
			detached: true
		}
	);
	let serverOutput = '';
	server.stdout.on('data', (d) => (serverOutput += d));
	server.stderr.on('data', (d) => (serverOutput += d));

	const errors = [];
	let browser;
	try {
		await waitForServer(BASE + '/');
		browser = await chromium.launch();
		const page = await browser.newPage({ viewport: DESKTOP });
		page.on('pageerror', (e) => errors.push(String(e)));
		page.on('console', (msg) => {
			if (msg.type() === 'error') errors.push(msg.text());
		});

		// no backend runs during capture -- `/tables` gets a fixed listing instead of a failed
		// fetch (which would also trip the console-error check below). fetch-only: the `/tables`
		// page navigation matches the same glob.
		await page.route('**/tables', (route) =>
			route.request().resourceType() === 'fetch'
				? route.fulfill({ json: { tables: LOBBY_TABLES } })
				: route.fallback()
		);
		// root +layout.svelte's ApiConnectGate polls GET /healthz before rendering any page --
		// only `?mock=`/`/demo` skip it client-side, and `lobby`/`tables` above intentionally
		// don't use `?mock=` (they're not table-scoped), so this stands in for the missing backend.
		await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));

		for (const { name, url, before, viewport } of PAGES) {
			await page.setViewportSize(viewport ?? DESKTOP);
			await page.goto(BASE + url, { waitUntil: 'networkidle' });
			// ApiConnectGate holds the "Connecting…" panel for a minimum of 1s even once /healthz
			// (mocked above) resolves instantly -- wait it out so the screenshot captures the
			// actual page, not the connecting overlay mid-fade.
			await page.locator('.connect-gate').waitFor({ state: 'detached' });
			if (before) await before(page);
			const dest = path.join(OUT_DIR, `${name}.png`);
			const viewportOnly = viewport === PHONE || viewport === PHONE_LANDSCAPE;
			await page.screenshot({ path: dest, fullPage: !viewportOnly });
			console.log('captured', dest);
		}
	} finally {
		if (browser) await browser.close();
		if (server.pid) {
			try {
				process.kill(-server.pid, 'SIGTERM');
			} catch {
				// already gone
			}
		}
	}

	if (errors.length) {
		console.error('Page/console errors seen during capture:');
		for (const e of errors) console.error(' -', e);
		console.error('\nDev server output (for context):\n' + serverOutput.slice(-2000));
		process.exit(1); // explicit exit: killing vite's process group doesn't always release
		// every fd our own stdio pipes hold, so leaving this to natural event-loop drain can hang
	}

	console.log(`\nWrote ${PAGES.length} screenshots to ${path.relative(REPO_ROOT, OUT_DIR)}/`);
	console.log('Remember to update README.md’s Screenshots section if pages were added/removed.');
	process.exit(0); // see the note above the error-path exit -- this script doesn't reliably
	// drain the event loop on its own after killing the dev server's process group
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
