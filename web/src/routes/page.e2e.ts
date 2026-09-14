import { expect, test } from '@playwright/test';

test('home page loads and has a title', async ({ page }) => {
	const response = await page.goto('/');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle(/Mahjong/);
});

test('lobby route renders', async ({ page }) => {
	const response = await page.goto('/lobby');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Lobby');
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
