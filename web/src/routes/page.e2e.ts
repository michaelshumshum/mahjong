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

test('chat demo: picking a canned phrase appends it to the scrollback', async ({ page }) => {
	await page.goto('/');
	await page.waitForLoadState('networkidle');

	const chat = page.locator('.chat');
	await expect(chat.locator('.entry-phrase', { hasText: 'Good game' })).toBeVisible(); // seeded

	await chat.getByRole('button', { name: 'Nice hand!' }).click();
	await expect(chat.locator('.entry-phrase', { hasText: 'Nice hand!' })).toBeVisible();
});

test('settings demo: toggling pre-arm and motion prefs fires onChange with the new values', async ({
	page
}) => {
	await page.goto('/');
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
	await page.goto('/');
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
	await page.goto('/');
	await page.waitForLoadState('networkidle');

	await page.getByRole('button', { name: 'Push "Copied" (1.5s)' }).click();
	const toast = page.locator('.toast', { hasText: 'Copied to clipboard' });
	await expect(toast).toBeVisible();
	await expect(toast).toHaveCount(0, { timeout: 3000 });
});

test('lobby route renders', async ({ page }) => {
	const response = await page.goto('/lobby');
	expect(response?.status()).toBe(200);
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
