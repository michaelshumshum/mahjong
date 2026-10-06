import { expect, test } from '@playwright/test';

test('demo page loads', async ({ page }) => {
	const response = await page.goto('/demo');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle(/Mahjong/);
});

test('claim buttons demo: choosing an option reports the right one, disambiguated chows included', async ({
	page
}) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Chow: 5 Bamboo, 7 Bamboo' }).click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: chow 5s-7s');

	await page.getByRole('button', { name: 'Pass', exact: true }).click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass');
});

test('settings demo: toggling pre-arm and motion prefs fires onChange with the new values', async ({
	page
}) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	await expect(page.getByTestId('auto-arm-summary')).toHaveText(
		'no_calls=false auto_pass_chow=false'
	);

	await page.getByLabel('No calls this hand').check();
	await expect(page.getByTestId('auto-arm-summary')).toHaveText(
		'no_calls=true auto_pass_chow=false'
	);

	await page.getByLabel('Reduce motion').check();
	await expect(page.getByTestId('prefs-summary')).toHaveText('soundEnabled=true motion=reduced');
});

test('toast demo: pushed toasts render and can be dismissed manually', async ({ page }) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Push "Reconnecting…"' }).click();
	const toast = page.locator('.toast', { hasText: 'Reconnecting…' });
	await expect(toast).toBeVisible();

	await toast.getByRole('button', { name: 'Dismiss' }).click();
	await expect(toast).toHaveCount(0);
});

test('toast demo: a short-duration toast auto-dismisses without manual interaction', async ({
	page
}) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Push "Copied" (1.5s)' }).click();
	const toast = page.locator('.toast', { hasText: 'Copied to clipboard' });
	await expect(toast).toBeVisible();
	await expect(toast).toHaveCount(0, { timeout: 3000 });
});

test('score sheet demo: expanding a win round reveals its winning hand, a draw round shows no winning hand', async ({
	page
}) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	const scoreSheet = page.locator('.score-sheet');
	// row order is deterministic (hand 1, 2, 3, 4) -- indexing by row avoids matching a
	// substring of some other row's delta/running-total figures (e.g. "2" inside "-24").
	const rows = scoreSheet.locator('tbody tr');

	// hand 2 (row index 1) has no per-round detail -- no expand affordance for it at all.
	await expect(rows.nth(1).locator('.round-expand')).toHaveCount(0);

	// hand 1 (row index 0): a real win -- expanding reveals winning hand tiles and faan patterns.
	const round1Toggle = rows.nth(0).locator('.round-expand');
	await expect(scoreSheet.locator('#round-detail-1')).toHaveCount(0);
	await round1Toggle.click();
	const detail1 = scoreSheet.locator('#round-detail-1');
	await expect(detail1).toBeVisible();
	await expect(detail1).toContainText('Half Flush');
	await expect(detail1).toContainText('Total 3 faan');
	await expect(detail1.locator('.tile')).not.toHaveCount(0);
	await expect(round1Toggle).toHaveAttribute('aria-expanded', 'true');

	// collapsing hides it again.
	await round1Toggle.click();
	await expect(scoreSheet.locator('#round-detail-1')).toHaveCount(0);
	await expect(round1Toggle).toHaveAttribute('aria-expanded', 'false');

	// hand 3 (row index 2): an exhaustive draw -- expandable, but with a plain note instead of a
	// winning hand.
	const round3Toggle = rows.nth(2).locator('.round-expand');
	await round3Toggle.click();
	const detail3 = scoreSheet.locator('#round-detail-3');
	await expect(detail3).toContainText('Exhaustive draw');
	await expect(detail3.locator('.tile')).toHaveCount(0);
});
