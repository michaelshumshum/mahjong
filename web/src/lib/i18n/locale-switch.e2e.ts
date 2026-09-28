import { expect, test } from '@playwright/test';

// LocaleSwitcher lives in Settings, reachable with no backend via the demo page's SettingsDemo
// section (ApiConnectGate skips /demo), proving the full round trip: click -> cookie -> SSR zh-Hant.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
});

test('switching locale via the UI writes the cookie and re-renders zh-Hant, surviving a reload', async ({
	page,
	context
}) => {
	await page.goto('/demo');
	await page.waitForLoadState('networkidle');

	// each locale option renders its own label in its own language regardless of current locale,
	// so these two names are stable across both directions of the switch.
	const englishOption = page.getByRole('radio', { name: 'English' });
	const zhHantOption = page.getByRole('radio', { name: '繁體中文' });
	await expect(englishOption).toBeChecked();

	await zhHantOption.check();
	await page.waitForLoadState('networkidle'); // setLocale's default reload: true

	const cookies = await context.cookies();
	expect(cookies.find((c) => c.name === 'PARAGLIDE_LOCALE')?.value).toBe('zh-Hant');
	await expect(page.getByRole('radio', { name: '繁體中文' })).toBeChecked();

	// the lobby's real (non-demo, ApiConnectGate-gated) copy actually renders in zh-Hant: the
	// sr-only heading and the primary CTA.
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await expect(page.locator('h1')).toHaveText('麻雀');
	await expect(page.getByTestId('lobby-create-table')).toHaveText('開枱');
	await expect(page.getByTestId('lobby-practice-bots')).toHaveText('對戰機械人');

	// persistence: a plain reload re-reads the same cookie, no re-selection needed.
	await page.reload();
	await page.waitForLoadState('networkidle');
	await expect(page.locator('h1')).toHaveText('麻雀');
});

test('defaults to English lobby copy with no locale cookie set', async ({ page }) => {
	await page.goto('/');
	await page.waitForLoadState('networkidle');

	await expect(page.locator('h1')).toHaveText('Mahjong');
	await expect(page.getByTestId('lobby-create-table')).toHaveText('Create a table');
});
