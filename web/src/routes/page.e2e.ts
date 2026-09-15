import { expect, test } from '@playwright/test';

test('home page loads and has a title', async ({ page }) => {
	const response = await page.goto('/');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle(/Mahjong/);
});

test('claim buttons demo: choosing an option reports the right one, disambiguated chows included', async ({
	page
}) => {
	await page.goto('/');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Chow 5s-7s' }).click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: chow 5s-7s');

	await page.getByRole('button', { name: 'Pass', exact: true }).click();
	await expect(page.getByTestId('claim-choice')).toHaveText('chose: pass');
});

test('lobby route renders', async ({ page }) => {
	const response = await page.goto('/lobby');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Lobby');
});

test('lobby create room shows a mock invite code', async ({ page }) => {
	await page.goto('/lobby');
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
	await page.goto('/lobby');
	await page.waitForLoadState('networkidle');
	await page.getByLabel('Invite code').fill('abc123');
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
