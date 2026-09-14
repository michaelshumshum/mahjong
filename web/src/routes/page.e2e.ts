import { expect, test } from '@playwright/test';

test('home page loads and has a title', async ({ page }) => {
	await page.goto('/');
	await expect(page).toHaveTitle(/Mahjong/);
});
