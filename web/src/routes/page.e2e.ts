import { expect, test } from '@playwright/test';

test('home page loads and has a title', async ({ page }) => {
	const response = await page.goto('/');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle(/Mahjong/);
});

test('lobby create room shows a mock invite code', async ({ page }) => {
	await page.goto('/');
	// wait past hydration: the create button is server-rendered but its click handler only
	// attaches once svelte-kit finishes loading, so an immediate click can race it.
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Create room' }).click();

	const code = page.getByTestId('hosted-code');
	await expect(code).toBeVisible();
	await expect(code).toHaveText(/^[A-Z0-9]{6}$/);

	await page.getByRole('button', { name: 'Enter room' }).click();
	await expect(page).toHaveURL(/\/table\/[A-Z0-9]{6}$/);
});

test('lobby join room navigates to the table route with the entered code', async ({ page }) => {
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await page.getByPlaceholder('ABC123').fill('ABC123');
	await page.getByRole('button', { name: 'Join room' }).click();

	await expect(page).toHaveURL('/table/ABC123');
	await expect(page.locator('h1')).toHaveText('Table');
});

test('table route renders', async ({ page }) => {
	const response = await page.goto('/table/abc123');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Table');
});

test('replay route renders', async ({ page }) => {
	const response = await page.goto('/replay/abc123');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Replay');
});

test('profile route renders', async ({ page }) => {
	const response = await page.goto('/profile');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Profile');
});
