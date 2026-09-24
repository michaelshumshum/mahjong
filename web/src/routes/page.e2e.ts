import { expect, test } from '@playwright/test';

// every route is gated behind ApiConnectGate's /healthz poll (root +layout.svelte) -- this suite
// has no real backend (playwright.config.ts's webServer is `pnpm dev` alone), so every test needs
// this mocked or the gate would poll to its 10s timeout and never render the page under test.
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

test('shows an error with a retry button when the API never becomes healthy', async ({ page }) => {
	await page.unroute('**/healthz');
	let healthy = false;
	await page.route('**/healthz', (route) =>
		healthy
			? route.fulfill({ json: { status: 'ok' } })
			: route.fulfill({ status: 503, json: { status: 'draining' } })
	);
	await page.goto('/');

	await expect(page.getByText("Can't reach the server.")).toBeVisible({ timeout: 15_000 });
	healthy = true;
	await page.getByRole('button', { name: 'Retry' }).click();

	await expect(page.getByRole('button', { name: 'Create a table' })).toBeVisible();
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
	await page.getByRole('button', { name: 'Create a table' }).click();

	await expect(page.getByRole('dialog', { name: 'Create a table' })).toBeVisible();
	await page.getByRole('button', { name: 'Create', exact: true }).click();

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
	await page.getByRole('button', { name: 'Create a table' }).click();

	const dialog = page.getByRole('dialog', { name: 'Create a table' });
	await dialog.locator('input[type="radio"][value="custom"]').check();
	await dialog.getByLabel('Minimum faan').selectOption('0');
	await dialog.getByRole('button', { name: 'Create', exact: true }).click();

	await expect(page).toHaveURL('/table/CUSTOM1');
	expect(sentBody).toMatchObject({ ruleset: 'custom' });
	expect((sentBody as unknown as { rules: Record<string, unknown> }).rules).toMatchObject({
		min_faan: 0,
		multi_win: false
	});
});

test('lobby practice vs bots navigates straight to a practice table, no dialog', async ({
	page
}) => {
	await mockCreateTable(page, 'XYZ789');
	await page.goto('/');
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Practice vs Bots' }).click();

	await expect(page).toHaveURL('/table/XYZ789?practice=1');
});

test('lobby join a game link opens the tables page', async ({ page }) => {
	await page.goto('/');
	await page.getByRole('link', { name: 'Join a game' }).click();
	await expect(page).toHaveURL('/tables');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tables');
});

test('tables page join navigates to the table route with the entered code', async ({ page }) => {
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByPlaceholder('ABC123').fill('ABC123');
	await page.getByRole('button', { name: 'Join table' }).click();

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

	await cards.nth(1).getByRole('button', { name: 'Watch' }).click();
	await expect(page).toHaveURL('/table/LIVE22');

	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByRole('button', { name: 'Sit down' }).click();
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
	await card.getByRole('button', { name: 'Rejoin' }).click();
	await expect(page).toHaveURL('/table/REJOIN');
});
