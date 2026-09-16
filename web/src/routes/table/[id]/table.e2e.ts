import { expect, test } from '@playwright/test';

// Covers the mock-driven /table scene assembly (docs/03-frontend.md §3): each mock scenario
// renders without layout errors, switching scenarios actually changes what's on screen, a
// claim-window interaction works end to end, and the sub-768px collapse structurally applies.

test('table route renders the default (your-turn) scenario without errors', async ({ page }) => {
	const errors: string[] = [];
	page.on('pageerror', (err) => errors.push(err.message));

	const response = await page.goto('/table/abc123');
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
	await page.goto('/table/abc123');
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
	await page.goto('/table/abc123');
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
	await page.goto('/table/abc123');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).toHaveCSS('position', 'fixed');
});

test('desktop-width viewport does not apply the fixed self-hand collapse', async ({ page }) => {
	await page.setViewportSize({ width: 1280, height: 800 });
	await page.goto('/table/abc123');
	await page.waitForLoadState('networkidle');

	const selfRegion = page.locator('.seat-region--self');
	await expect(selfRegion).not.toHaveCSS('position', 'fixed');
});
