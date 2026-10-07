import { expect, test } from '@playwright/test';

// Covers mock-driven /table scene assembly: scenarios render without layout errors, switching
// scenarios updates the screen, claim interaction works end to end, sub-768px collapse applies.

test('table route renders the default (your-turn) scenario without errors', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (err) => errors.push(err.message));

	const response = await page.goto('/table/abc123?mock=1');
	expect(response?.status()).toBe(200);
	await page.waitForLoadState('networkidle');

	await expect(page.locator('h1')).toHaveText('Table');
	await expect(page.getByTestId('table-scene')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Your turn to discard' })).toHaveAttribute(
		'aria-pressed',
		'true'
	);
	// no live claim window or hand result in this scenario
	await expect(page.getByTestId('claim-overlay')).toHaveCount(0);
	await expect(page.getByTestId('faan-overlay')).toHaveCount(0);
	expect(errors).toEqual([]);
	// mock scenarios are frozen snapshots, not live turn state -- always the generic table title.
	await expect(page).toHaveTitle('Table abc123 · Mahjong');
});

test('switching to the claim-window scenario surfaces claim buttons, and choosing one records the choice', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Claim window open (you)' }).click();

	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.locator('.claim-btn--win')).toBeVisible();
	await expect(overlay.locator('.claim-btn--pung')).toBeVisible();

	await overlay.locator('.claim-btn--win').click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: win');
});

test('leaving the claim window untouched auto-passes once its timer runs out', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Claim window open (you)' }).click();
	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();

	// fixed durationMs is 5000ms -- no click, just wait it out to prove the dialog's own timer
	// (not a manual choice) fires the pass.
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass', { timeout: 7000 });
});

test('switching to the hand-ended scenario shows the faan breakdown', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand just ended' }).click();

	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.getByRole('heading', { name: /wins$/ })).toBeVisible();
	// the hold's countdown lives in the panel header, not floating above it.
	await expect(overlay.locator('.hand-end-header [role="timer"]')).toBeVisible();
	// the hand is over: no seat may still wear the turn halo behind the overlay.
	await expect(page.locator('.seat-plate--turn')).toHaveCount(0);
});

test('switching to the hand-ended-in-a-draw scenario shows the plain draw summary', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand ended in a draw' }).click();

	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();
	await expect(page.getByTestId('hand-end-draw')).toBeVisible();
	await expect(page.getByTestId('hand-end-draw').getByText('Draw')).toBeVisible();
});

test('switching to the game-ended scenario auto-shows the game-end summary, not the hand-end hold', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Game just ended' }).click();

	// the game-end screen replaces the last hand's own hold overlay outright -- gameJustEnded's
	// handResult is null, matching the real wire sequence.
	await expect(page.getByTestId('faan-overlay')).toHaveCount(0);
	const overlay = page.getByTestId('game-end-overlay');
	await expect(overlay).toBeVisible();
	await expect(page.locator('.seat-plate--turn')).toHaveCount(0);
	await expect(overlay.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/');
	await expect(overlay.getByRole('heading', { name: 'Game over', exact: true })).toBeVisible();
	// gameJustEnded's You and Carol both finish on -30: a shared 3rd, not 3rd and 4th.
	await expect(overlay.getByTestId('game-end-you-placed')).toHaveText('You tied for 3rd');
	await expect(overlay.locator('.final-row')).toHaveCount(4);
	await expect(overlay.locator('.final-rank')).toHaveText(['1st', '2nd', '3rd', '3rd']);
	// not a practice table: nothing to replay.
	await expect(overlay.getByTestId('game-end-play-again')).toHaveCount(0);

	// score sheet shows all 4 rounds; final standings cards are omitted in favor of the podium.
	await expect(overlay.locator('.score-sheet tbody tr')).toHaveCount(4);
	await expect(overlay.locator('.standings')).toHaveCount(0);

	// clicking into a past round (hand 2, a self-drawn All Pungs win) reveals that round's own
	// winning hand, not just the most recent one.
	const round2Toggle = overlay.locator('.score-sheet tbody tr').nth(1).locator('.round-expand');
	await round2Toggle.click();
	const detail2 = overlay.locator('#round-detail-2');
	await expect(detail2).toContainText('All Pungs');
	await expect(detail2).toContainText('Total 4 faan');
	await expect(detail2.locator('.tile')).not.toHaveCount(0);
	await round2Toggle.click(); // collapse before indexing into row 2 (hand 3) below

	// an exhaustive-draw round (hand 3) expands to a plain note, no winning hand.
	const round3Toggle = overlay.locator('.score-sheet tbody tr').nth(2).locator('.round-expand');
	await round3Toggle.click();
	const detail3 = overlay.locator('#round-detail-3');
	await expect(detail3).toContainText('Exhaustive draw');
	await expect(detail3.locator('.tile')).toHaveCount(0);
});

test('dismissing the hand-end hold in mock mode closes it locally with no socket round trip', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand just ended' }).click();
	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();

	await overlay.getByTestId('close-button').click();
	await expect(overlay).toHaveCount(0);

	// switching scenarios resets the local dismiss -- a fresh hand-end always starts open.
	await page.getByRole('button', { name: 'Hand ended in a draw' }).click();
	await expect(page.getByTestId('faan-overlay')).toBeVisible();
});

test('leaving the hand-end hold untouched auto-closes it once its timer runs out', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand just ended' }).click();
	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();

	// handJustEnded's fixed handEndHoldMs is 8000ms (mock-game-state.ts) -- no Close click, just
	// wait it out to prove the dialog's own timer dismisses it the same way the button would.
	await expect(overlay).toHaveCount(0, { timeout: 10000 });
});

test('phone-width viewport applies the sub-768px sticky collapse to the self hand region', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).toHaveCSS('position', 'sticky');
});

// the hand sizes to its container (docs/frontend.md §3). 390 pushed the drawn tile off-screen, 1024
// under the right strip; 390x700 makes the page outgrow the viewport, so the self row must stick.
for (const [width, height] of [
	[390, 844],
	[390, 700],
	[1024, 768]
] as const) {
	test(`the full hand and drawn tile fit inside the viewport at ${width}x${height}`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=your-turn');
		await page.waitForLoadState('networkidle');

		const tiles = page.locator('.seat-region--self .hand-tile');
		await expect(tiles).toHaveCount(14);
		const last = await tiles.last().boundingBox();
		const drawn = await page.locator('.seat-region--self .hand-tile--drawn').boundingBox();
		for (const box of [last, drawn]) {
			expect(box).not.toBeNull();
			expect(box!.x).toBeGreaterThanOrEqual(0);
			expect(box!.x + box!.width).toBeLessThanOrEqual(width);
			expect(box!.y + box!.height).toBeLessThanOrEqual(height);
		}
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
			width
		);

		if (width >= 768) {
			const right = await page.locator('.seat-region--right').boundingBox();
			expect(last!.x + last!.width).toBeLessThanOrEqual(right!.x);
		}
	});
}

test('phone mock toolbar collapses the scenario picker into a disclosure with the same buttons', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const disclosure = page.getByTestId('scenario-disclosure');
	await expect(disclosure).not.toHaveAttribute('open');
	await expect(page.getByRole('button', { name: 'Hand just ended' })).toBeHidden();
	await disclosure.locator('summary').click();
	await page.getByRole('button', { name: 'Hand just ended' }).click();
	await expect(page.getByTestId('faan-overlay')).toBeVisible();
	await expect(disclosure).not.toHaveAttribute('open');
	await expect(disclosure.locator('summary')).toContainText('Hand just ended');
});

test('desktop-width viewport does not apply the sticky self-hand collapse', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).not.toHaveCSS('position', 'sticky');
});

// proves clientPrefs/autoArm persistence survives an actual reload, not just unit-level save/load
// (settings-storage.spec.ts). autoArm's reconnect re-assert needs a real socket -- see live.e2e.ts.
test('reloading the page preserves clientPrefs toggled in Settings', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByTestId('toggle-settings').click();
	const soundToggle = page.getByRole('checkbox', { name: 'Sound effects' });
	const reducedMotion = page.getByRole('radio', { name: 'Reduce motion' });
	await expect(soundToggle).toBeChecked(); // default is on
	await soundToggle.uncheck();
	await reducedMotion.check();

	await page.reload();
	await page.waitForLoadState('networkidle');
	await page.getByTestId('toggle-settings').click();

	await expect(page.getByRole('checkbox', { name: 'Sound effects' })).not.toBeChecked();
	await expect(page.getByRole('radio', { name: 'Reduce motion' })).toBeChecked();
});

test('the motion setting drives html[data-motion] and overrides prefers-reduced-motion', async ({
	page
}) => {
	await page.emulateMedia({ reducedMotion: 'reduce' });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const html = page.locator('html');
	// CenterHub (P1.2) now carries the acting seat's timer ring, not the seat header.
	const ring = page.locator('.hub-marker-ring .progress').first();
	await expect(html).toHaveAttribute('data-motion', 'system');
	await expect(ring).toHaveCSS('animation-name', 'none');

	await page.getByTestId('toggle-settings').click();
	await page.getByRole('radio', { name: 'Full motion' }).check();
	await expect(html).toHaveAttribute('data-motion', 'full');
	await expect(ring).not.toHaveCSS('animation-name', 'none');

	await page.emulateMedia({ reducedMotion: 'no-preference' });
	await page.getByRole('radio', { name: 'Reduce motion' }).check();
	await expect(html).toHaveAttribute('data-motion', 'reduced');
	await expect(ring).toHaveCSS('animation-name', 'none');

	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect(html).toHaveAttribute('data-motion', 'reduced');
});

// Covers the scripted draw/discard/claim/kong animation demo -- the pure slot-resolution
// algorithm is unit-tested in tile-slots.spec.ts; this proves it's wired up end to end.
test('animation demo: draw, discard, claim, and concealed kong run the full sequence without errors', async ({
	page
}) => {
	const errors: string[] = [];
	page.on('pageerror', (err) => errors.push(err.message));

	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Animate a turn' }).click();

	const demo = page.getByTestId('animation-demo');
	await expect(demo).toBeVisible();
	const opponentBacks = demo.locator('.backs-row .demo-slot');
	await expect(opponentBacks).toHaveCount(13);

	// draw: 13 -> 14 concealed slots
	await demo.getByRole('button', { name: 'Draw' }).click();
	await expect(opponentBacks).toHaveCount(14);

	// discard: the drawn slot leaves (transitionend commits it), back down to 13, and it's
	// now sitting in the discard pool as a revealed tile
	await demo.getByRole('button', { name: 'Discard', exact: true }).click();
	await expect(opponentBacks).toHaveCount(13, { timeout: 2000 });
	await expect(demo.locator('.discard-pool .discard-tile')).toHaveCount(1);

	// claim: that discard becomes an exposed pung meld, and leaves the discard pool
	await demo.getByRole('button', { name: 'You claim last discard (pung)' }).click();
	await expect(demo.locator('.discard-pool .discard-tile')).toHaveCount(0);
	await expect(demo.locator('.meld-row .meld')).toHaveCount(1);

	// concealed kong: 13 -> 9 concealed slots, a second meld appears
	await demo.getByRole('button', { name: 'Concealed kong' }).click();
	await expect(opponentBacks).toHaveCount(9);
	await expect(demo.locator('.meld-row .meld')).toHaveCount(2);

	// your own discard: pick a hand tile, it leaves your hand and lands in your discard pool
	const yourHand = page.getByTestId('demo-your-hand');
	const yourDiscards = page.getByTestId('demo-your-discards');
	await expect(yourHand.locator('.demo-hand-tile')).toHaveCount(5);
	await yourHand.locator('.demo-hand-tile').first().click();
	await expect(yourHand.locator('.demo-hand-tile')).toHaveCount(4, { timeout: 2000 });
	await expect(yourDiscards.locator('.discard-tile')).toHaveCount(1);

	await demo.getByRole('button', { name: 'Reset demo' }).click();
	await expect(opponentBacks).toHaveCount(13);
	await expect(yourHand.locator('.demo-hand-tile')).toHaveCount(5);

	expect(errors).toEqual([]);
});

test('waiting room invite copies the table link and resets its label after 2s', async ({
	page,
	context
}) => {
	await context.grantPermissions(['clipboard-read', 'clipboard-write']);
	// desktop chromium has no share sheet; pin that so the clipboard fallback is what runs.
	await page.addInitScript(() => {
		Object.defineProperty(navigator, 'share', { value: undefined, configurable: true });
	});
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.goto('/table/abc123?pregame=waiting');

	await expect(page.getByTestId('pretable-code')).toHaveText('abc123');
	const invite = page.getByTestId('pretable-invite');
	await invite.click();
	await expect(invite).toHaveText('Link copied');
	expect(await page.evaluate(() => navigator.clipboard.readText())).toContain(
		'/table/abc123?pregame=waiting'
	);
	await expect(invite).toHaveText('Invite friends', { timeout: 4000 });
});

test('practice game end offers Play again, re-creating a table with the last bot levels', async ({
	page
}) => {
	await page.addInitScript(() => {
		localStorage.setItem(
			'mahjong:practiceSetup:v1',
			JSON.stringify({ 1: 'easy', 2: 'impossible', 3: 'normal' })
		);
	});
	let body: unknown = null;
	await page.route('**/tables', async (route) => {
		body = route.request().postDataJSON();
		await route.fulfill({ json: { table_id: 'AGAIN1', ruleset_preset: null, ruleset: {} } });
	});
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.goto('/table/abc123?mock=1&practice=1');
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Game just ended' }).click();

	await page.getByTestId('game-end-play-again').click();
	await expect(page).toHaveURL('/table/AGAIN1?practice=1');
	expect(body).toEqual({ practice: true, bot_tiers: { 1: 'T1', 2: 'ORACLE', 3: 'T2' } });
});

test('the toolbar Guide button opens the faan guide in-game', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('open-guide').click();
	await expect(page.getByTestId('guide-panel')).toBeVisible();
	await page.getByTestId('guide-dialog').getByTestId('close-button').click();
	await expect(page.getByTestId('guide-panel')).toHaveCount(0);
});

test('native modal dialogs: Escape closes a panel and returns focus to its opener', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const opener = page.getByTestId('toggle-settings');
	await opener.focus();
	await page.keyboard.press('Enter');
	const dialog = page.getByRole('dialog', { name: 'Settings' });
	await expect(dialog).toBeVisible();
	// showModal(): top layer, rest of the page inert.
	expect(await page.evaluate(() => document.querySelector('dialog')?.matches(':modal'))).toBe(true);

	await page.keyboard.press('Escape');
	await expect(dialog).toHaveCount(0);
	await expect(opener).toBeFocused();
});

test('claim dialog: focus starts on Pass and Escape passes', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Claim window open (you)' }).click();

	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.locator('.claim-btn--pass')).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass');
	// the mock keeps the frozen offer up; the dialog itself must not have closed natively.
	await expect(overlay).toBeVisible();
});

test('hand-end hold closes on Escape; the game-end summary does not', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand just ended' }).click();
	const handEnd = page.getByTestId('faan-overlay');
	await expect(handEnd).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(handEnd).toHaveCount(0);

	await page.getByRole('button', { name: 'Game just ended' }).click();
	const gameEnd = page.getByTestId('game-end-overlay');
	await expect(gameEnd).toBeVisible();
	await page.keyboard.press('Escape');
	await page.keyboard.press('Escape');
	await expect(gameEnd).toBeVisible();
	await expect(gameEnd.getByRole('heading', { name: 'Game over', exact: true })).toBeVisible();
});
