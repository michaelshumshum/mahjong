import { expect, test } from '@playwright/test';

// every route is gated behind ApiConnectGate's /healthz poll -- this suite has no real backend
// (webServer is `pnpm dev` alone), so every test must mock it or the gate polls to its 10s timeout.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
});

test('home page loads and has a title', async ({ page }) => {
	const response = await page.goto('/');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle(/Mahjong/);
});

test('shows a connecting screen until the API health check succeeds, then the lobby', async ({
	page
}) => {
	await page.unroute('**/healthz');
	await page.route('**/healthz', async (route) => {
		await new Promise((resolve) => setTimeout(resolve, 300));
		await route.fulfill({ json: { status: 'ok' } });
	});
	await page.goto('/');

	await expect(page.getByText('Connecting…')).toBeVisible();
	await expect(page.getByRole('button', { name: 'Create a table' })).toBeVisible();
	await expect(page.getByText('Connecting…')).not.toBeVisible();
});

// Exhausting all 10 attempts (511s total) isn't feasible in e2e -- unit-tested with fake timers
// in lobby.spec.ts instead. This only exercises the first real retry cycle in a live browser.
test('retries after a failed attempt, showing the attempt count and next-retry countdown', async ({
	page
}) => {
	await page.unroute('**/healthz');
	await page.route('**/healthz', (route) =>
		route.fulfill({ status: 503, json: { status: 'draining' } })
	);
	await page.goto('/');

	await expect(page.getByText('Connecting…')).toBeVisible();
	await expect(page.getByText(/^Attempt \d+$/)).not.toBeVisible();
	// attempt 1 just failed -- a 1s timeout raced the real 1s backoff 1:1 with no CI slack.
	await expect(page.getByText('Next attempt in 1s')).toBeVisible({ timeout: 3_000 });
	await expect(page.getByText('Attempt 2')).toBeVisible({ timeout: 3_000 });
	// attempt 2 also failed -- next delay doubled to 2s, proving the backoff actually grows.
	await expect(page.getByText('Next attempt in 2s')).toBeVisible({ timeout: 3_000 });
	await expect(page.getByText('Attempt 3')).toBeVisible({ timeout: 4_000 });
});

// this suite has no real backend behind it (playwright.config.ts's webServer is `pnpm dev`
// alone), so every test that creates a table mocks the POST /tables response.
function mockCreateTable(page: import('@playwright/test').Page, tableId: string) {
	return page.route('**/tables', (route) => {
		if (route.request().method() !== 'POST') return route.fallback();
		return route.fulfill({
			json: { table_id: tableId, ruleset_preset: 'hk_classic', ruleset: {} }
		});
	});
}

test('lobby create table opens a rules dialog, then navigates to the created table', async ({
	page
}) => {
	await mockCreateTable(page, 'ABC123');
	await page.goto('/');
	// wait past hydration: the create button is server-rendered but its click handler only
	// attaches once svelte-kit finishes loading, so an immediate click can race it.
	await page.waitForLoadState('networkidle');
	await page.getByTestId('lobby-create-table').click();

	await expect(page.getByTestId('create-table-dialog')).toBeVisible();
	await page.getByTestId('create-table-submit').click();

	await expect(page).toHaveURL('/table/ABC123');
});

test('lobby create table with custom rules sends the edited RuleSet, never multi_win', async ({
	page
}) => {
	let sentBody: Record<string, unknown> | null = null;
	await page.route('**/tables', (route) => {
		if (route.request().method() !== 'POST') return route.fallback();
		sentBody = route.request().postDataJSON();
		return route.fulfill({
			json: { table_id: 'CUSTOM1', ruleset_preset: null, ruleset: sentBody?.rules ?? {} }
		});
	});
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('lobby-create-table').click();

	const dialog = page.getByTestId('create-table-dialog');
	await dialog.locator('input[type="radio"][value="custom"]').check();
	await dialog.getByLabel('Minimum faan').selectOption('0');
	await dialog.getByTestId('create-table-submit').click();

	await expect(page).toHaveURL('/table/CUSTOM1');
	expect(sentBody).toMatchObject({ ruleset: 'custom' });
	expect((sentBody as unknown as { rules: Record<string, unknown> }).rules).toMatchObject({
		min_faan: 0,
		multi_win: false
	});
});

test('lobby practice vs bots opens a difficulty dialog, then navigates to the practice table', async ({
	page
}) => {
	await mockCreateTable(page, 'XYZ789');
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('lobby-practice-bots').click();

	await expect(page.getByTestId('practice-setup-dialog')).toBeVisible();
	await page.getByTestId('practice-start-submit').click();

	await expect(page).toHaveURL('/table/XYZ789?practice=1');
});

test('lobby practice vs bots sends the chosen per-seat difficulty', async ({ page }) => {
	let sentBody: Record<string, unknown> | null = null;
	await page.route('**/tables', (route) => {
		if (route.request().method() !== 'POST') return route.fallback();
		sentBody = route.request().postDataJSON();
		return route.fulfill({
			json: { table_id: 'DIFF456', ruleset_preset: 'hk_classic', ruleset: {} }
		});
	});
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('lobby-practice-bots').click();

	const dialog = page.getByTestId('practice-setup-dialog');
	// each seat's difficulty cycles easy -> normal -> impossible -> easy on click, starting from
	// the default (Normal).
	const rightSlot = dialog.getByTestId('practice-difficulty-right');
	const leftSlot = dialog.getByTestId('practice-difficulty-left');
	await rightSlot.click();
	await rightSlot.click();
	await leftSlot.click();
	await dialog.getByTestId('practice-start-submit').click();

	await expect(page).toHaveURL('/table/DIFF456?practice=1');
	expect(sentBody).toMatchObject({
		practice: true,
		bot_tiers: { 1: 'T1', 2: 'T2', 3: 'ORACLE' }
	});
});

test('lobby join a game link opens the tables page', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-join-game-link').click();
	await expect(page).toHaveURL('/tables');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tables');
});

test('tables page join navigates to the table route with the entered code', async ({ page }) => {
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('join-by-code-input').fill('ABC123');
	await page.getByTestId('join-by-code-submit').click();

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

test('tables page lists tables with sit-down for open ones and watch for ones in progress', async ({
	page
}) => {
	// fetch-only: the `/tables` page navigation matches the same glob
	await page.route('**/tables', (route) => {
		if (route.request().resourceType() !== 'fetch') return route.fallback();
		return route.fulfill({
			json: {
				tables: [
					{
						id: 'LIVE22',
						status: 'in_progress',
						hand_no: 3,
						seats: [
							{ status: 'connected', name: 'Mei' },
							{ status: 'bot', name: 'FaanBot' },
							{ status: 'bot', name: 'FaanBot' },
							{ status: 'bot', name: 'FaanBot' }
						]
					},
					{
						id: 'OPEN11',
						status: 'open',
						hand_no: 1,
						seats: [
							{ status: 'connected', name: 'Alice' },
							{ status: 'empty', name: null },
							{ status: 'empty', name: null },
							{ status: 'empty', name: null }
						]
					}
				]
			}
		});
	});
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');

	const cards = page.getByTestId('table-card');
	await expect(cards).toHaveCount(2);
	// open tables sort first
	await expect(cards.nth(0)).toContainText('OPEN11');
	await expect(cards.nth(0)).toContainText('Open · 1/4');
	await expect(cards.nth(1)).toContainText('In progress · hand 3');

	await cards.nth(1).getByTestId('table-card-action').click();
	await expect(page).toHaveURL('/table/LIVE22');

	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	// open tables sort first, same as above
	await page.getByTestId('table-card').first().getByTestId('table-card-action').click();
	await expect(page).toHaveURL('/table/OPEN11');
});

test('tables page shows Rejoin for a table this browser has joined before', async ({ page }) => {
	await page.route('**/tables', (route) => {
		if (route.request().resourceType() !== 'fetch') return route.fallback();
		return route.fulfill({
			json: {
				tables: [
					{
						id: 'REJOIN',
						status: 'in_progress',
						hand_no: 2,
						seats: [
							{ status: 'disconnected', name: 'Alice' },
							{ status: 'connected', name: 'Bob' },
							{ status: 'empty', name: null },
							{ status: 'empty', name: null }
						]
					}
				]
			}
		});
	});
	// seed a persisted seat so the card treats this table as already joined
	await page.addInitScript(() => {
		localStorage.setItem(
			'mahjong:seat:v2:REJOIN',
			JSON.stringify({ seat: 0, savedAt: Date.now() })
		);
	});
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');

	const card = page.getByTestId('table-card');
	await expect(card).toContainText('REJOIN');
	await card.getByTestId('table-card-action').click();
	await expect(page).toHaveURL('/table/REJOIN');
});

test('guide button opens a faan library with a tab per faan count', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-guide').click();
	await expect(page.getByTestId('guide-dialog')).toBeVisible();
	await expect(page.getByTestId('guide-entry').first()).toContainText('All Sequences');
	await page.getByTestId('guide-tab-6').click();
	await expect(page.getByTestId('guide-panel')).toContainText('Full Flush');
	await page.getByTestId('guide-tab-limit').click();
	await expect(page.getByTestId('guide-panel')).toContainText('Thirteen Orphans');
});

test('guide ruleset filter hides patterns a preset disables', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-guide').click();
	await page.getByTestId('guide-tab-4').click();
	await expect(page.getByTestId('guide-panel')).toContainText('Seven Pairs');
	await page.getByTestId('guide-ruleset').selectOption('hk_strict');
	await expect(page.getByTestId('guide-panel')).toContainText('Mixed Terminals');
	await expect(page.getByTestId('guide-panel')).not.toContainText('Seven Pairs');
	await page.getByTestId('guide-ruleset').selectOption('');
	await expect(page.getByTestId('guide-panel')).toContainText('Seven Pairs');
});

test('language button on the lobby switches to zh-Hant and back', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-language').click();
	await expect(page.locator('html')).toHaveAttribute('lang', 'zh-Hant');
	await page.getByTestId('lobby-language').click();
	await expect(page.locator('html')).toHaveAttribute('lang', 'en');
});
