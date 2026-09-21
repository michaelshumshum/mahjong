#!/usr/bin/env node
// Regression-test driver for the declare-button click bug (Win / Concealed kong / Added kong
// silently not sending their `declare` frame on click -- see `.declare-actions button`'s
// `:active` override in `src/routes/table/[id]/+page.svelte` and its comment for the root
// cause). A real Playwright browser is the only way to catch this class of bug: it's a CSS
// press-transform moving the button out from under a held-then-released pointer so the
// click's real DOM target becomes the button's own wrapper `<div>`, not the button -- a
// wire-level test never touches the button at all, so it can't regress here.
//
// Spawned as a subprocess by `server/tests/test_declare_actions_live_ui.py`, which needs to be
// the one rigging the rare hand (`get_table()` + `dataclasses.replace`, same technique
// `server/tests/test_reconnect.py` uses) since that requires living in the same process as the
// real backend -- a plain Node/Playwright test can't reach into that process's memory. This
// script only drives the browser: 4 real seats (no bots), reading `PAGE_LOADED`/`GO` off
// stdin/stdout as the handshake for "rig now, between everyone connecting and anyone joining".
//
// Usage: node scripts/live-declare-click.mjs <baseUrl> <tableId> <buttonNameRegex>
// Prints one `PAGE_LOADED` line once all 4 pages have connected (before any joins), waits for
// a `GO` line on stdin, then joins all 4 seats and clicks the named button on seat 0's page.
// Prints one final `RESULT <json>` line: `{ framesSent: string[] }` -- every WS frame seat 0's
// page sent after the click.

import { chromium } from 'playwright';
import readline from 'node:readline';

const args = process.argv.slice(2);
if (args.length !== 3) {
	console.error('usage: live-declare-click.mjs <baseUrl> <tableId> <buttonNameRegex>');
	process.exit(2);
}
const [base, table, buttonNamePattern] = args;

function waitForStdinLine(expected) {
	return new Promise((resolve) => {
		const rl = readline.createInterface({ input: process.stdin });
		rl.on('line', (line) => {
			if (line.trim() === expected) {
				rl.close();
				resolve();
			}
		});
	});
}

const browser = await chromium.launch();
const pages = await Promise.all(
	Array.from({ length: 4 }, async () => (await browser.newContext()).newPage())
);

const wsFrames = [];
pages[0].on('websocket', (ws) => {
	if (!ws.url().includes('/ws')) return;
	ws.on('framesent', (f) => wsFrames.push(f.payload));
});

await Promise.all(pages.map((p) => p.goto(`${base}/table/${table}`, { waitUntil: 'networkidle' })));

// signal the rig point: every page has connected (creating the table) but none has joined yet.
console.log('PAGE_LOADED');
await waitForStdinLine('GO');

const names = ['Alice', 'Bob', 'Carol', 'Dave'];
for (const [i, p] of pages.entries()) {
	await p.locator('#display-name-input').fill(names[i]);
}
await pages[0].getByRole('button', { name: 'Sit down' }).click();
await pages[0].getByText(/You're seated as/).waitFor({ timeout: 15000 });
for (const p of pages.slice(1)) {
	await p.getByRole('button', { name: 'Sit down' }).click();
}

const btn = pages[0].getByRole('button', { name: new RegExp(buttonNamePattern) });
await btn.waitFor({ state: 'visible', timeout: 30000 });

const framesBefore = wsFrames.length;
await btn.click();
await pages[0].waitForTimeout(1500);

console.log('RESULT ' + JSON.stringify({ framesSent: wsFrames.slice(framesBefore) }));

await browser.close();
// `readline` on `process.stdin` (the PAGE_LOADED/GO handshake above) leaves stdin referenced
// and the event loop alive even after `rl.close()` -- exit explicitly rather than rely on
// natural completion, or the parent (`server/tests/test_declare_actions_live_ui.py`) has to
// wait out its own subprocess timeout and SIGTERM this process itself.
process.exit(0);
