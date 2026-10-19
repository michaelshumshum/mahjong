import { expect, test } from '@playwright/test';

// Covers mock-driven /table scene assembly: scenarios (picked by `?mock=<id>`) render without
// layout errors, claim interaction works end to end, sub-768px collapse applies.

test('table route renders the default (your-turn) scenario without errors', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (err) => errors.push(err.message));

	const response = await page.goto('/table/abc123?mock=1');
	expect(response?.status()).toBe(200);
	await page.waitForLoadState('networkidle');

	await expect(page.locator('h1')).toHaveText('Table');
	await expect(page.getByTestId('table-scene')).toBeVisible();
	// mock mode wears the real rail -- there is no scenario picker.
	await expect(page.locator('.table-code')).toHaveText('abc123');
	// no live claim window or hand result in this scenario
	await expect(page.getByTestId('claim-overlay')).toHaveCount(0);
	await expect(page.getByTestId('faan-overlay')).toHaveCount(0);
	expect(errors).toEqual([]);
	// mock scenarios are frozen snapshots, not live turn state -- always the generic table title.
	await expect(page).toHaveTitle('Table abc123 · Hoi Toi');
});

test('leaving the table via client-side navigation drops the table title', async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.goto('/table/abc123?mock=1');
	await expect(page).toHaveTitle('Table abc123 · Hoi Toi');
	// svelte never restores document.title on unmount, so the next page has to set its own.
	await page.evaluate(() => {
		const a = document.createElement('a');
		a.href = '/';
		document.body.append(a);
		a.click();
	});
	await expect(page).toHaveURL('/');
	await expect(page).toHaveTitle('Hoi Toi');
});

test('switching to the claim-window scenario surfaces claim buttons, and choosing one records the choice', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=claim-window');
	await page.waitForLoadState('networkidle');

	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.locator('.claim-btn--win')).toBeVisible();
	await expect(overlay.locator('.claim-btn--pung')).toBeVisible();

	await overlay.locator('.claim-btn--win').click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: win');
});

test('leaving the claim window untouched auto-passes once its timer runs out', async ({ page }) => {
	await page.goto('/table/abc123?mock=claim-window');
	await page.waitForLoadState('networkidle');
	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();

	// fixed durationMs is 5000ms -- no click, just wait it out to prove the dialog's own timer
	// (not a manual choice) fires the pass.
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass', { timeout: 7000 });
});

test('switching to the hand-ended scenario shows the faan breakdown', async ({ page }) => {
	await page.goto('/table/abc123?mock=hand-ended');
	await page.waitForLoadState('networkidle');

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
	await page.goto('/table/abc123?mock=hand-ended-draw');
	await page.waitForLoadState('networkidle');

	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();
	await expect(page.getByTestId('hand-end-draw')).toBeVisible();
	await expect(page.getByTestId('hand-end-draw').getByText('Draw')).toBeVisible();
});

test('a provable-fairness hand end checks the reveal against its commit', async ({ page }) => {
	await page.goto('/table/abc123?mock=hand-ended-draw');
	await page.waitForLoadState('networkidle');

	const badge = page.getByTestId('fairness-badge');
	await expect(badge).toHaveAttribute('data-check', 'verified');
	await expect(badge.getByText('Fair deal verified')).toBeVisible();
});

test('switching to the game-ended scenario auto-shows the game-end summary, not the hand-end hold', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=game-ended');
	await page.waitForLoadState('networkidle');

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
	await page.goto('/table/abc123?mock=hand-ended');
	await page.waitForLoadState('networkidle');
	const overlay = page.getByTestId('faan-overlay');
	await expect(overlay).toBeVisible();

	await overlay.getByTestId('close-button').click();
	await expect(overlay).toHaveCount(0);

	// another scenario's hand-end starts open again.
	await page.goto('/table/abc123?mock=hand-ended-draw');
	await expect(page.getByTestId('faan-overlay')).toBeVisible();
});

test('leaving the hand-end hold untouched auto-closes it once its timer runs out', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=hand-ended');
	await page.waitForLoadState('networkidle');
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

// the hand sizes to its container (docs/frontend.md §3). 390x700 outgrows the viewport, so the self
// row must stick; 844x390 is a phone held sideways (compact landscape, no page scroll).
const VIEWPORTS = [
	[390, 844],
	[390, 700],
	[844, 390],
	[1024, 768],
	[1440, 900]
] as const;

for (const [width, height] of VIEWPORTS) {
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

		// tablet-up only: short landscape stacks the opponents in a side column instead.
		if (width >= 768 && height > 500) {
			const right = await page.locator('.seat-region--right').boundingBox();
			expect(last!.x + last!.width).toBeLessThanOrEqual(right!.x);
		}
	});
}

test('a portrait phone wraps the hand into two rows of non-overlapping tiles', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=your-turn');
	await page.waitForLoadState('networkidle');

	const boxes = await page
		.locator('.seat-region--self .hand-tile-slot')
		.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON()));
	expect(boxes).toHaveLength(14);
	expect(new Set(boxes.map((b) => Math.round(b.top))).size).toBe(2);
	// rows sit flush (--hand-gap), no lift reservation between them.
	expect(boxes[8].top - boxes[0].bottom).toBeLessThanOrEqual(3);
	for (const [i, a] of boxes.entries()) {
		expect(a.width).toBeGreaterThanOrEqual(36);
		for (const b of boxes.slice(i + 1)) {
			const overlap =
				a.left < b.right - 0.5 &&
				b.left < a.right - 0.5 &&
				a.top < b.bottom - 0.5 &&
				b.top < a.bottom - 0.5;
			expect(overlap).toBe(false);
		}
	}
});

test('portrait phone opponents are stacked full-width chip rows', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=your-turn');
	await page.waitForLoadState('networkidle');

	const boxes = [];
	for (const pos of ['left', 'across', 'right']) {
		boxes.push((await page.locator(`.seat-region--${pos}`).boundingBox())!);
	}
	for (const box of boxes) expect(box.width).toBeGreaterThan(300);
	expect(boxes[0].y + boxes[0].height).toBeLessThanOrEqual(boxes[1].y);
	expect(boxes[1].y + boxes[1].height).toBeLessThanOrEqual(boxes[2].y);
});

// phone: each opponent's pool sits under that chip's melds, joined to it, and above the next chip.
for (const [width, height] of [
	[390, 844],
	[844, 390]
] as const) {
	test(`each phone discard pool sits under its own seat at ${width}x${height}`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=late-hand');
		await page.waitForLoadState('networkidle');

		await expect(page.locator('.discard-pool')).toHaveCount(4);
		const seats = [];
		for (const pos of ['left', 'across', 'right']) {
			const chip = page.locator(`.seat-region--${pos}`);
			const meldBottoms = await chip
				.locator('.meld .mini-tile')
				.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().bottom));
			seats.push({
				chip: (await chip.boundingBox())!,
				meldBottom: Math.max(...meldBottoms),
				pool: (await page.locator(`.discard-pool--${pos}`).boundingBox())!
			});
		}
		for (const { chip, meldBottom, pool } of seats) {
			expect(pool.y).toBeGreaterThanOrEqual(meldBottom);
			expect(Math.abs(pool.y - (chip.y + chip.height))).toBeLessThanOrEqual(1);
			expect(pool.x).toBeCloseTo(chip.x, 0);
			// clear of any chip below it in the same column (landscape seats left and right apart).
			for (const other of seats) {
				const sameColumn =
					other.chip.x < pool.x + pool.width && pool.x < other.chip.x + other.chip.width;
				if (sameColumn && other.chip.y > chip.y)
					expect(pool.y + pool.height).toBeLessThanOrEqual(other.chip.y);
			}
		}

		const own = (await page.locator('.discard-pool--self').boundingBox())!;
		const hub = (await page.locator('.center-hub').boundingBox())!;
		expect(own.y).toBeGreaterThanOrEqual(hub.y + hub.height);
		if (height > width) {
			const bar = (await page.locator('.seat-region--self').boundingBox())!;
			expect(own.y + own.height).toBeLessThanOrEqual(bar.y);
		}

		const labels = await page
			.locator('.discard-pool')
			.evaluateAll((els) => els.map((el) => getComputedStyle(el, '::before').content));
		expect(labels).toEqual(['none', 'none', 'none', 'none']);
	});

	test(`the hand sits flush under the seat plate at ${width}x${height}`, async ({ page }) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=your-turn');
		await page.waitForLoadState('networkidle');

		const plate = (await page.locator('.seat-region--self .seat-plate').boundingBox())!;
		const tile = (await page.locator('.seat-region--self .hand-tile').first().boundingBox())!;
		expect(tile.y - (plate.y + plate.height)).toBeGreaterThanOrEqual(-0.5);
		expect(tile.y - (plate.y + plate.height)).toBeLessThanOrEqual(3);
	});
}

// late-hand: ~20 discards per pool and up to 4 melds + 3 flowers per opponent.
for (const [width, height] of [
	[390, 844],
	[360, 740],
	[844, 390],
	[667, 375]
] as const) {
	test(`a crowded late hand stays inside the viewport width at ${width}x${height}`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=late-hand');
		await page.waitForLoadState('networkidle');

		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
			width
		);
		const pools = page.locator('.discard-pool');
		await expect(pools).toHaveCount(4);
		for (const pool of await pools.all()) {
			const box = (await pool.boundingBox())!;
			const rights = await pool
				.locator('.discard-tile')
				.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().right));
			for (const right of rights) expect(right).toBeLessThanOrEqual(box.x + box.width + 0.5);
		}
		for (const pos of ['left', 'across', 'right']) {
			const chip = page.locator(`.seat-region--${pos}`);
			const box = (await chip.boundingBox())!;
			const rights = await chip
				.locator('.meld .mini-tile')
				.evaluateAll((els) => els.map((el) => el.getBoundingClientRect().right));
			for (const right of rights) expect(right).toBeLessThanOrEqual(box.x + box.width + 0.5);
		}
	});
}

test('a portrait phone keeps a 7-tile hand plus the drawn tile on one row', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/table/abc123?mock=late-hand');
	await page.waitForLoadState('networkidle');

	const tops = await page
		.locator('.seat-region--self .hand-tile-slot')
		.evaluateAll((els) => els.map((el) => Math.round(el.getBoundingClientRect().top)));
	expect(tops).toHaveLength(8);
	expect(new Set(tops).size).toBe(1);
});

test('phone landscape puts your melds on the seat plate row', async ({ page }) => {
	await page.setViewportSize({ width: 844, height: 390 });
	await page.goto('/table/abc123?mock=your-turn');
	await page.waitForLoadState('networkidle');

	const self = page.locator('.seat-region--self');
	const plate = (await self.locator('.seat-plate').boundingBox())!;
	const melds = (await self.locator('.meld-row').boundingBox())!;
	expect(melds.x).toBeGreaterThan(plate.x + plate.width);
	expect(melds.y).toBeLessThan(plate.y + plate.height);
	expect(melds.y + melds.height).toBeGreaterThan(plate.y);
});

for (const [width, height] of [
	[390, 844],
	[844, 390],
	[1024, 768],
	[1440, 900]
] as const) {
	test(`claim buttons are reachable with no horizontal scroll at ${width}x${height}`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=claim-window');
		await page.waitForLoadState('networkidle');

		const overlay = page.getByTestId('claim-overlay');
		await expect(overlay).toBeVisible();
		const buttons = overlay.locator('.claim-btn');
		await expect(buttons).not.toHaveCount(0);
		for (const button of await buttons.all()) {
			await button.scrollIntoViewIfNeeded();
			await expect(button).toBeInViewport({ ratio: 1 });
		}
		expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
			width
		);
		await overlay.locator('.claim-btn--pung').click();
		await expect(page.getByTestId('claim-choice')).toHaveText('chose: pung');
	});
}

test('phone landscape seats the table as a box with the hub in the header rail', async ({
	page
}) => {
	await page.setViewportSize({ width: 844, height: 390 });
	await page.goto('/table/abc123?mock=your-turn');
	await page.waitForLoadState('networkidle');

	await expect(page.locator('.center-hub')).toHaveCount(1);
	await expect(page.locator('.table-toolbar .center-hub')).toBeVisible();
	const box = async (sel: string) => (await page.locator(sel).boundingBox())!;
	const across = await box('.seat-region--across');
	const left = await box('.seat-region--left');
	const right = await box('.seat-region--right');
	const ownPool = await box('.discard-pool--self');
	const hand = await box('.seat-region--self');
	expect(left.y).toBeGreaterThan(across.y);
	expect(right.y).toBeCloseTo(left.y, 0);
	expect(right.x).toBeGreaterThan(left.x + left.width);
	expect(ownPool.y + ownPool.height).toBeLessThanOrEqual(hand.y + 0.5);
	expect(hand.y - (ownPool.y + ownPool.height)).toBeLessThanOrEqual(8);
});

// late-hand is the stress fixture: every seat and pool must be visible without scrolling.
for (const [width, height] of [
	[844, 390],
	[740, 360],
	[667, 375]
] as const) {
	test(`a crowded late hand fits a ${width}x${height} landscape phone without scrolling`, async ({
		page
	}) => {
		await page.setViewportSize({ width, height });
		await page.goto('/table/abc123?mock=late-hand');
		await page.waitForLoadState('networkidle');

		const surface = page.locator('.table-surface');
		const [scrollH, clientH] = await surface.evaluate((el) => [el.scrollHeight, el.clientHeight]);
		expect(scrollH).toBeLessThanOrEqual(clientH);
		for (const pos of ['across', 'left', 'right', 'self'])
			await expect(page.locator(`.discard-pool--${pos}`)).toBeInViewport({ ratio: 1 });
	});
}

test('phone landscape moves your melds beside a hand that has lost tiles to them', async ({
	page
}) => {
	await page.setViewportSize({ width: 844, height: 390 });
	await page.goto('/table/abc123?mock=late-hand');
	await page.waitForLoadState('networkidle');

	const self = page.locator('.seat-region--self');
	const hand = (await self.locator('.hand-row').boundingBox())!;
	const melds = (await self.locator('.meld-row').boundingBox())!;
	expect(melds.x).toBeGreaterThanOrEqual(hand.x + hand.width);
	expect(melds.y).toBeGreaterThan(hand.y);
});

test('phone landscape claim sheet leaves your hand visible', async ({ page }) => {
	await page.setViewportSize({ width: 844, height: 390 });
	await page.goto('/table/abc123?mock=claim-window');
	await page.waitForLoadState('networkidle');

	const sheet = (await page.locator('.claim-dialog').boundingBox())!;
	const tile = (await page.locator('.seat-region--self .hand-tile').first().boundingBox())!;
	expect(sheet.y).toBeLessThanOrEqual(1);
	expect(sheet.y + sheet.height).toBeLessThanOrEqual(tile.y);
});

test('phone landscape hand-end shows the payments and game-end the actions without scrolling', async ({
	page
}) => {
	await page.setViewportSize({ width: 740, height: 360 });
	await page.goto('/table/abc123?mock=hand-ended');
	await page.waitForLoadState('networkidle');
	await expect(page.locator('.payment-row').last()).toBeInViewport({ ratio: 1 });

	await page.goto('/table/abc123?mock=game-ended&practice=1');
	await page.waitForLoadState('networkidle');
	await expect(page.getByTestId('game-end-play-again')).toBeInViewport({ ratio: 1 });
	await expect(page.getByTestId('game-end-standings')).toBeInViewport({ ratio: 1 });
});

test('short landscape fits hand, centre and opponents without page scroll', async ({ page }) => {
	await page.setViewportSize({ width: 844, height: 390 });
	await page.goto('/table/abc123?mock=your-turn');
	await page.waitForLoadState('networkidle');

	expect(await page.evaluate(() => document.documentElement.scrollHeight)).toBeLessThanOrEqual(390);
	for (const selector of [
		'.seat-region--across',
		'.seat-region--left',
		'.seat-region--right',
		'.center-hub',
		'.discard-pool--across',
		'.discard-pool--left',
		'.discard-pool--right',
		'.discard-pool--self',
		'.seat-region--self'
	]) {
		await expect(page.locator(selector)).toBeInViewport({ ratio: 1 });
	}
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
	await page.getByRole('tab', { name: 'Display', exact: true }).click();
	const soundToggle = page.getByRole('switch', { name: 'Sound effects' });
	const reducedMotion = page.getByRole('radio', { name: 'Reduce motion' });
	await expect(soundToggle).toBeChecked(); // default is on
	await soundToggle.uncheck();
	await reducedMotion.check();

	await page.reload();
	await page.waitForLoadState('networkidle');
	await page.getByTestId('toggle-settings').click();
	await page.getByRole('tab', { name: 'Display', exact: true }).click();

	await expect(page.getByRole('switch', { name: 'Sound effects' })).not.toBeChecked();
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
	await page.getByRole('tab', { name: 'Display', exact: true }).click();
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

test('the tile size setting scales hand and discard tiles and survives a reload', async ({
	page
}) => {
	await page.goto('/table/abc123?mock=1');
	await page.waitForLoadState('networkidle');

	const html = page.locator('html');
	const handTile = page.locator('.seat-region--self .hand-tile-slot').first();
	const discard = page.locator('.discard-tile').first();
	await expect(html).toHaveAttribute('data-tile-size', 'medium');
	const before = { hand: (await handTile.boundingBox())!, discard: (await discard.boundingBox())! };

	await page.getByTestId('toggle-settings').click();
	await page.getByRole('tab', { name: 'Display', exact: true }).click();
	await page.getByRole('radio', { name: 'Large' }).check();
	await expect(html).toHaveAttribute('data-tile-size', 'large');
	const after = { hand: (await handTile.boundingBox())!, discard: (await discard.boundingBox())! };
	expect(after.hand.width).toBeGreaterThan(before.hand.width);
	expect(after.discard.height).toBeGreaterThan(before.discard.height);

	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect(html).toHaveAttribute('data-tile-size', 'large');
});

// Covers the scripted draw/discard/claim/kong animation demo -- the pure slot-resolution
// algorithm is unit-tested in tile-slots.spec.ts; this proves it's wired up end to end.
test('animation demo: draw, discard, claim, and concealed kong run the full sequence without errors', async ({
	page
}) => {
	const errors: string[] = [];
	page.on('pageerror', (err) => errors.push(err.message));

	await page.goto('/demo');
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
			JSON.stringify({ 1: 'easy', 2: 'impossible', 3: 'expert' })
		);
	});
	let body: unknown = null;
	await page.route('**/tables', async (route) => {
		body = route.request().postDataJSON();
		await route.fulfill({ json: { table_id: 'AGAIN1', ruleset_preset: null, ruleset: {} } });
	});
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.goto('/table/abc123?mock=game-ended&practice=1');
	await page.waitForLoadState('networkidle');

	await page.getByTestId('game-end-play-again').click();
	await expect(page).toHaveURL('/table/AGAIN1?practice=1');
	expect(body).toEqual({ practice: true, bot_tiers: { 1: 'T1', 2: 'ORACLE', 3: 'T4' } });
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
	await page.goto('/table/abc123?mock=claim-window');
	await page.waitForLoadState('networkidle');

	const overlay = page.getByTestId('claim-overlay');
	await expect(overlay).toBeVisible();
	await expect(overlay.locator('.claim-btn--pass')).toBeFocused();
	await page.keyboard.press('Escape');
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass');
	// the mock keeps the frozen offer up; the dialog itself must not have closed natively.
	await expect(overlay).toBeVisible();
});

test('hand-end hold closes on Escape; the game-end summary does not', async ({ page }) => {
	await page.goto('/table/abc123?mock=hand-ended');
	await page.waitForLoadState('networkidle');
	const handEnd = page.getByTestId('faan-overlay');
	await expect(handEnd).toBeVisible();
	await page.keyboard.press('Escape');
	await expect(handEnd).toHaveCount(0);

	await page.goto('/table/abc123?mock=game-ended');
	const gameEnd = page.getByTestId('game-end-overlay');
	await expect(gameEnd).toBeVisible();
	await page.keyboard.press('Escape');
	await page.keyboard.press('Escape');
	await expect(gameEnd).toBeVisible();
	await expect(gameEnd.getByRole('heading', { name: 'Game over', exact: true })).toBeVisible();
});
