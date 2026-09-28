import { expect, test } from '@playwright/test';

// hooks.server.ts's `paraglideMiddleware` rewrites app.html's `%paraglide.lang%`/`%paraglide.dir%`
// placeholders server-side (08-i18n-plan.md's "File layout") -- nothing client-side ever touches
// `<html lang>` afterwards (Paraglide's runtime never writes `documentElement.lang`), so the raw
// SSR response body is the right thing to assert on here, not the hydrated DOM. `request` fetches
// the real dev server started by playwright.config.ts's `webServer`, equivalent to `curl`ing it
// with an explicit `Cookie` header per locale.
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
