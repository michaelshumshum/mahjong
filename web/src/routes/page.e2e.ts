import { expect, test, type Locator, type Page } from '@playwright/test';

// every route is gated behind ApiConnectGate's /healthz poll -- this suite has no real backend
// (webServer is `pnpm dev` alone), so every test must mock it or the gate polls to its 10s timeout.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
});

test('home page loads and has a title', async ({ page }) => {
	const response = await page.goto('/');
	expect(response?.status()).toBe(200);
	await expect(page).toHaveTitle('Hoi Toi');
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
	await expect(page.getByRole('link', { name: 'Play online' })).toBeVisible();
	await expect(page.getByText('Connecting…')).not.toBeVisible();
});

// the gate holds for at least 1s (MIN_DISPLAY_MS), so a lobby link visible within 500ms of the
// navigation means the gate never showed.
const GATE_ABSENT_MS = 500;

test('a client-side navigation from /status to the lobby skips the connecting screen', async ({
	page
}) => {
	await page.goto('/status');
	await page.waitForLoadState('networkidle');
	await page.getByRole('link', { name: 'Lobby' }).click();

	await expect(page).toHaveURL('/');
	await expect(page.getByRole('link', { name: 'Play online' })).toBeVisible({
		timeout: GATE_ABSENT_MS
	});
});

test('returning to the lobby from /status after a gated load skips the connecting screen', async ({
	page
}) => {
	await page.goto('/');
	await expect(page.getByRole('link', { name: 'Play online' })).toBeVisible();
	await page.waitForLoadState('networkidle');
	await page.getByTestId('lobby-status-link').click();
	await expect(page).toHaveURL('/status');
	await page.waitForLoadState('networkidle');
	await page.getByRole('link', { name: 'Lobby' }).click();

	await expect(page).toHaveURL('/');
	await expect(page.getByRole('link', { name: 'Play online' })).toBeVisible({
		timeout: GATE_ABSENT_MS
	});
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

test('lobby play online leads to create table, which opens a rules dialog, then navigates to the created table', async ({
	page
}) => {
	await mockCreateTable(page, 'ABC123');
	await page.goto('/');
	await page.getByTestId('lobby-play-online').click();
	await expect(page).toHaveURL('/tables');
	// wait past hydration: the create button is server-rendered but its click handler only
	// attaches once svelte-kit finishes loading, so an immediate click can race it.
	await page.waitForLoadState('networkidle');
	await page.getByTestId('tables-header-create-table').click();

	await expect(page.getByTestId('create-table-dialog')).toBeVisible();
	await page.getByTestId('create-table-submit').click();

	await expect(page).toHaveURL('/table/ABC123');
});

async function captureCreateBody(page: Page): Promise<{ body: Record<string, unknown> | null }> {
	const sent: { body: Record<string, unknown> | null } = { body: null };
	await page.route('**/tables', (route) => {
		if (route.request().method() !== 'POST') return route.fallback();
		sent.body = route.request().postDataJSON();
		return route.fulfill({
			json: { table_id: 'CUSTOM1', ruleset_preset: null, ruleset: sent.body?.rules ?? {} }
		});
	});
	return sent;
}

test('create table private switch sends private: true', async ({ page }) => {
	const sent = await captureCreateBody(page);
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('tables-header-create-table').click();
	const dialog = page.getByTestId('create-table-dialog');
	const toggle = dialog.getByRole('switch', { name: 'Private table' });
	await expect(toggle).not.toBeChecked();
	await toggle.click({ force: true });
	await dialog.getByTestId('create-table-submit').click();

	await expect(page).toHaveURL('/table/CUSTOM1');
	expect(sent.body).toMatchObject({ ruleset: 'hk_classic', private: true });
});

async function openCustomRules(page: Page): Promise<Locator> {
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('tables-header-create-table').click();
	const dialog = page.getByTestId('create-table-dialog');
	// click, not check(): choosing Custom swaps the view, unmounting the radio
	await dialog.locator('input[type="radio"][value="custom"]').click();
	await expect(dialog.getByRole('heading', { name: 'Custom rules' })).toBeVisible();
	return dialog;
}

test('lobby create table with custom rules sends the edited RuleSet, inert fields at defaults', async ({
	page
}) => {
	const sent = await captureCreateBody(page);
	const dialog = await openCustomRules(page);

	await dialog
		.getByRole('group', { name: 'Minimum faan' })
		.getByRole('radio', { name: '0', exact: true })
		.click({ force: true });
	await dialog.getByTestId('rules-tab-hands').click();
	await dialog.getByRole('button', { name: 'Add override' }).click();
	await dialog.getByTestId('override-pattern').selectOption('自摸');
	await dialog.getByTestId('override-value').fill('2');
	await dialog.getByTestId('rules-tab-table').click();
	await dialog.getByRole('switch', { name: /Provable fairness/ }).click({ force: true });
	await expect(dialog.getByText('3 changes from HK Classic')).toBeVisible();
	await dialog.getByTestId('create-table-submit').click();

	await expect(page).toHaveURL('/table/CUSTOM1');
	expect(sent.body).toMatchObject({ ruleset: 'custom' });
	expect((sent.body as { rules: Record<string, unknown> }).rules).toMatchObject({
		min_faan: 0,
		faan_overrides: { 自摸: 2 },
		provable_fairness: true,
		multi_win: false,
		pao_rules: false,
		tenpai_payments: false,
		self_draw_multiplier: 1.5
	});
});

test('custom rules start from the chosen preset, and reset can be undone', async ({ page }) => {
	const dialog = await openCustomRules(page);
	const startFrom = dialog.getByRole('group', { name: 'Start from' });
	const faanCap = dialog.getByRole('group', { name: 'Faan cap' });

	await startFrom.getByRole('radio', { name: 'Casual' }).click({ force: true });
	await expect(faanCap.getByRole('radio', { name: '13' })).toBeChecked();
	await faanCap.getByRole('radio', { name: '8' }).click({ force: true });
	await expect(dialog.getByText('1 change from Casual')).toBeVisible();

	await dialog.getByTestId('create-table-reset').click();
	await expect(faanCap.getByRole('radio', { name: '13' })).toBeChecked();
	await dialog.getByRole('button', { name: 'Undo' }).click();
	await expect(faanCap.getByRole('radio', { name: '8' })).toBeChecked();
});

test('an invalid custom rule blocks create and jumps to its tab', async ({ page }) => {
	const sent = await captureCreateBody(page);
	const dialog = await openCustomRules(page);

	await dialog.getByTestId('rules-tab-table').click();
	await dialog.getByTestId('rule-turn_seconds').fill('');
	await dialog.getByTestId('rules-tab-scoring').click();
	await dialog.getByTestId('create-table-submit').click();

	await expect(dialog.getByText('Some rules need fixing')).toBeVisible();
	await expect(dialog.getByTestId('rule-turn_seconds')).toBeFocused();
	expect(sent.body).toBeNull();

	await dialog.getByRole('button', { name: 'Increase Turn' }).click();
	await dialog.getByTestId('create-table-submit').click();
	await expect(page).toHaveURL('/table/CUSTOM1');
	expect((sent.body as { rules: Record<string, unknown> }).rules).toMatchObject({
		turn_seconds: 6
	});
});

test('the create dialog reopens on the last custom setup', async ({ page }) => {
	await captureCreateBody(page);
	const dialog = await openCustomRules(page);
	await dialog
		.getByRole('group', { name: 'Start from' })
		.getByRole('radio', { name: 'Strict' })
		.click({ force: true });
	await dialog.getByTestId('rules-tab-play').click();
	await dialog.getByRole('switch', { name: /Dealer repeats on draw/ }).click({ force: true });
	await dialog.getByTestId('create-table-submit').click();
	await expect(page).toHaveURL('/table/CUSTOM1');

	await page.goto('/tables');
	await page.waitForLoadState('networkidle');
	await page.getByTestId('tables-header-create-table').click();
	const reopened = page.getByTestId('create-table-dialog');
	await expect(reopened.locator('input[type="radio"][value="custom"]')).toBeChecked();
	await expect(reopened.getByText('Based on Strict · 1 change')).toBeVisible();
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
	// each seat's difficulty cycles easy -> normal -> expert -> impossible -> easy on click,
	// starting from the default (Normal).
	const rightSlot = dialog.getByTestId('practice-difficulty-right');
	const acrossSlot = dialog.getByTestId('practice-difficulty-across');
	const leftSlot = dialog.getByTestId('practice-difficulty-left');
	await rightSlot.click();
	await rightSlot.click();
	await rightSlot.click();
	await acrossSlot.click();
	await leftSlot.click();
	await leftSlot.click();
	await dialog.getByTestId('practice-start-submit').click();

	await expect(page).toHaveURL('/table/DIFF456?practice=1');
	expect(sentBody).toMatchObject({
		practice: true,
		bot_tiers: { 1: 'T1', 2: 'T4', 3: 'ORACLE' }
	});
});

test('lobby play online opens the tables page', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-play-online').click();
	await expect(page).toHaveURL('/tables');
	await expect(page.getByRole('heading', { level: 1 })).toHaveText('Tables');
	await expect(page).toHaveTitle('Tables · Hoi Toi');
	// client-side nav back: the lobby must set its own title, not inherit the previous page's.
	await page.getByRole('link', { name: 'Lobby' }).click();
	await expect(page).toHaveURL('/');
	await expect(page).toHaveTitle('Hoi Toi');
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
	await expect(page).toHaveTitle('Replay · Hoi Toi');
});

test('profile route renders', async ({ page }) => {
	const response = await page.goto('/profile');
	expect(response?.status()).toBe(200);
	await expect(page.locator('h1')).toHaveText('Profile');
	await expect(page).toHaveTitle('Profile · Hoi Toi');
});

test('unknown route renders the error page with a status title', async ({ page }) => {
	const response = await page.goto('/no-such-page');
	expect(response?.status()).toBe(404);
	await expect(page.locator('h1')).toHaveText('404');
	await expect(page).toHaveTitle('404 · Hoi Toi');
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

test('tables page empty state offers to create a table, and stamps the last refresh', async ({
	page
}) => {
	await page.route('**/tables', (route) =>
		route.request().resourceType() === 'fetch'
			? route.fulfill({ json: { tables: [] } })
			: route.fallback()
	);
	await page.goto('/tables');

	await expect(page.getByTestId('tables-empty')).toBeVisible();
	await expect(page.getByTestId('tables-updated')).toContainText('Updated');
	await page.getByTestId('tables-create-table').click();
	await expect(page.getByTestId('create-table-dialog')).toBeVisible();
});

test('tables page offers create table in the header while tables are listed', async ({ page }) => {
	await page.route('**/tables', (route) =>
		route.request().resourceType() === 'fetch'
			? route.fulfill({
					json: {
						tables: [
							{
								id: 'OPEN22',
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
				})
			: route.fallback()
	);
	await page.goto('/tables');
	await page.waitForLoadState('networkidle');

	await expect(page.getByTestId('table-card')).toHaveCount(1);
	await expect(page.getByTestId('tables-empty')).toHaveCount(0);
	await page.getByTestId('tables-header-create-table').click();
	await expect(page.getByTestId('create-table-dialog')).toBeVisible();
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

test('guide dialog keeps its height across tabs', async ({ page }) => {
	await page.goto('/');
	await page.getByTestId('lobby-guide').click();
	const dialog = page.getByTestId('guide-dialog');
	const before = (await dialog.boundingBox())!.height;
	for (const tab of ['3', '8', 'limit']) {
		await page.getByTestId(`guide-tab-${tab}`).click();
		expect((await dialog.boundingBox())!.height).toBe(before);
	}
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
