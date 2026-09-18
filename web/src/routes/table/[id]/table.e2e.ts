import { expect, test } from '@playwright/test';

// Covers the mock-driven /table scene assembly (docs/03-frontend.md §3): each mock scenario
// renders without layout errors, switching scenarios actually changes what's on screen, a
// claim-window interaction works end to end, and the sub-768px collapse structurally applies.

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
	await expect(overlay.getByRole('button', { name: 'Win' })).toBeVisible();
	await expect(overlay.getByRole('button', { name: /^Pung/ })).toBeVisible();

	await overlay.getByRole('button', { name: 'Win' }).click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: win');
});

test('switching to the hand-ended scenario shows the faan breakdown', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Hand just ended' }).click();

	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.getByRole('heading', { name: /wins$/ })).toBeVisible();
});

test('phone-width viewport applies the sub-768px collapse to the self hand region', async ({
	page
}) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).toHaveCSS('position', 'fixed');
});

test('desktop-width viewport does not apply the fixed self-hand collapse', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).not.toHaveCSS('position', 'fixed');
});

// lib/ui/settings-storage.ts persists clientPrefs/autoArm to localStorage independent of the
// mock/live split (docs/03-frontend.md §6 "Settings persistence") -- this proves the round trip
// survives an actual page reload, not just the unit-level save/load pair
// (settings-storage.spec.ts). autoArm's re-assert-on-reconnect half needs a real socket to
// observe, which is what RUN_LIVE_BACKEND_TESTS=1 tests (live.e2e.ts) are for; not duplicated
// here.
test('reloading the page preserves clientPrefs toggled in Settings', async ({ page }) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Settings' }).click();
	const soundToggle = page.getByRole('checkbox', { name: 'Sound effects' });
	const reducedMotion = page.getByRole('radio', { name: 'Reduce motion' });
	await expect(soundToggle).toBeChecked(); // default is on
	await soundToggle.uncheck();
	await reducedMotion.check();

	await page.reload();
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Settings' }).click();

	await expect(page.getByRole('checkbox', { name: 'Sound effects' })).not.toBeChecked();
	await expect(page.getByRole('radio', { name: 'Reduce motion' })).toBeChecked();
});

// Covers the scripted draw/discard/claim/kong animation demo (docs/03-frontend.md §4's
// positional slot-identity rule) — the pure slot-resolution algorithm is unit-tested in
// tile-slots.spec.ts; this proves it's actually wired up and reachable end to end.
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
