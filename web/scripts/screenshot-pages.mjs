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
const BASE = `http://localhost:${PORT}`;

// The "notable pages" list — keep this curated and small (this is what ends up in the
// README), not exhaustive. Add a page here when it becomes a meaningful, stable part of the
// app; don't add every mock scenario or every intermediate dev-toolbar state.
const PAGES = [
	{ name: 'home', url: '/' },
	{ name: 'lobby', url: '/lobby' },
	// `?mock=1` is required now that `/table/[id]` defaults to opening a real WebSocket against
	// `[id]` as a room id (docs/03-frontend.md §6) -- there's no backend running during a
	// screenshot capture, so these opt into the frozen MOCK_SCENARIOS fixture path explicitly
	// rather than relying on it being the unauthenticated default.
	{ name: 'table-your-turn', url: '/table/demo123?mock=1' },
	{
		name: 'table-claim-window',
		url: '/table/demo123?mock=1',
		async before(page) {
			await page.getByRole('button', { name: 'Claim window open (you)' }).click();
		}
	},
	{
		name: 'table-hand-ended',
		url: '/table/demo123?mock=1',
		async before(page) {
			await page.getByRole('button', { name: 'Hand just ended' }).click();
			await page.waitForTimeout(150); // FaanBreakdown's own entrance, not a fixed animation wait
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
	const server = spawn('pnpm', ['exec', 'vite', 'dev', '--port', String(PORT), '--strictPort'], {
		cwd: WEB_DIR,
		stdio: ['ignore', 'pipe', 'pipe'],
		detached: true
	});
	let serverOutput = '';
	server.stdout.on('data', (d) => (serverOutput += d));
	server.stderr.on('data', (d) => (serverOutput += d));

	const errors = [];
	let browser;
	try {
		await waitForServer(BASE + '/');
		browser = await chromium.launch();
		const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
		page.on('pageerror', (e) => errors.push(String(e)));
		page.on('console', (msg) => {
			if (msg.type() === 'error') errors.push(msg.text());
		});

		for (const { name, url, before } of PAGES) {
			await page.goto(BASE + url, { waitUntil: 'networkidle' });
			if (before) await before(page);
			const dest = path.join(OUT_DIR, `${name}.png`);
			await page.screenshot({ path: dest, fullPage: true });
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
