import { expect, test } from '@playwright/test';

// nothing client-side ever writes `documentElement.lang`, so the raw SSR body (not the hydrated
// DOM) is what to assert on -- `request` hits the real preview server, like `curl` with a Cookie header.
test('SSR renders <html lang> from the baseLocale with no locale cookie', async ({ request }) => {
	const response = await request.get('/', { headers: { cookie: '' } });
	const html = await response.text();
	expect(html).toContain('<html lang="en" dir="ltr">');
});

test('SSR renders <html lang="zh-Hant"> when the PARAGLIDE_LOCALE cookie asks for it', async ({
	request
}) => {
	const response = await request.get('/', { headers: { cookie: 'PARAGLIDE_LOCALE=zh-Hant' } });
	const html = await response.text();
	expect(html).toContain('<html lang="zh-Hant" dir="ltr">');
});
