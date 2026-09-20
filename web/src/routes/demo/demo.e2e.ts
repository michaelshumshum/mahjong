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

	await page.getByRole('button', { name: 'Chow 5s-7s' }).click();
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
