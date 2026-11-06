import { expect, test } from '@playwright/test';

// /privacy and /terms skip ApiConnectGate; only the lobby test needs /healthz answered
const PAGES = [
	{ path: '/privacy', testId: 'privacy-page', en: 'Privacy policy', zh: '私隱政策' },
	{ path: '/terms', testId: 'terms-page', en: 'Terms of use', zh: '使用條款' }
];

for (const { path, testId, en, zh } of PAGES) {
	test(`${path} renders in English with no backend`, async ({ page }) => {
		const response = await page.goto(path);
		expect(response?.status()).toBe(200);
		await expect(page.getByTestId(testId)).toBeVisible();
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(en);
		await expect(page).toHaveTitle(`${en} · Hoi Toi`);
		await expect(page.getByTestId('legal-effective')).toContainText('November 6, 2026');
	});

	test(`${path} renders in zh-Hant from the locale cookie`, async ({ page, context, baseURL }) => {
		await context.addCookies([{ name: 'PARAGLIDE_LOCALE', value: 'zh-Hant', url: baseURL! }]);
		await page.goto(path);
		await expect(page.getByRole('heading', { level: 1 })).toHaveText(zh);
		await expect(page.getByTestId('legal-effective')).toContainText('2026年11月6日');
	});

	test(`${path} is in the server-rendered html`, async ({ request }) => {
		const html = await (await request.get(path)).text();
		expect(html).toContain(`data-testid="${testId}"`);
	});
}

test('without PUBLIC_CONTACT_EMAIL the contact links the GitHub issues', async ({ page }) => {
	await page.goto('/privacy');
	await expect(page.getByTestId('legal-contact')).toHaveAttribute(
		'href',
		'https://github.com/michaelshumshum/mahjong/issues'
	);
});

test('the two pages link each other', async ({ page }) => {
	await page.goto('/privacy');
	await page.getByTestId('legal-link-terms').click();
	await expect(page).toHaveURL('/terms');
	await expect(page.getByTestId('terms-page')).toBeVisible();
});

test('the lobby links both pages', async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.goto('/');
	await expect(page.getByTestId('lobby-privacy-link')).toHaveAttribute('href', '/privacy');
	await expect(page.getByTestId('lobby-terms-link')).toHaveAttribute('href', '/terms');
});
