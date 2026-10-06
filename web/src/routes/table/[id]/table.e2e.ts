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
	await expect(overlay.getByRole('link', { name: 'Back to home' })).toHaveAttribute('href', '/');

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

// the hand sizes to its container (docs/frontend.md §3); these two viewports used to push the
// drawn tile off-screen (390) and under the right opponent's strip (1024).
for (const [width, height] of [
	[390, 844],
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
	const ring = page.locator('.seat-region--self .progress').first();
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
