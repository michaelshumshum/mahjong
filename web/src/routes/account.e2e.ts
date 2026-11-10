import { readFile } from 'node:fs/promises';
import { expect, test, type Locator, type Page, type Route } from '@playwright/test';
import { ACCOUNTS_PORT } from '../../playwright.config';
import type { Me, MyGame, MyGamesPage } from '../lib/net/account';

// sign-in ui against a stubbed api: /me and /auth/* answered by page.route, never google
const ACCOUNTS = `http://localhost:${ACCOUNTS_PORT}`;
const API = 'http://localhost:8000';
const ANN: Me = {
	id: '00000000-0000-0000-0000-000000000001',
	display_name: 'Ann',
	created_at: '2026-11-01T00:00:00Z',
	training_consent_at: null,
	consent_version: null
};

// credentialed cors: the browser drops a response without these, as it would from the real api
function cors(route: Route): Record<string, string> {
	return {
		'Access-Control-Allow-Origin': route.request().headers()['origin'] ?? ACCOUNTS,
		'Access-Control-Allow-Credentials': 'true',
		'Access-Control-Allow-Methods': 'GET, POST, PATCH, DELETE',
		'Access-Control-Allow-Headers': 'Content-Type'
	};
}

function game(id: number, overrides: Partial<MyGame> = {}): MyGame {
	return {
		game_id: id,
		created_at: '2026-11-04T12:00:00Z',
		mode: 'practice',
		hand_count: 8,
		seat: 0,
		placement: 1,
		final_score: 40,
		others: [
			{ seat: 1, kind: 'bot', name: null, bot_tier: 'T4' },
			{ seat: 2, kind: 'user', name: 'Gone', bot_tier: null },
			{ seat: 3, kind: 'guest', name: null, bot_tier: null }
		],
		...overrides
	};
}

// two pages: 12 then 11, keyed by the `before` cursor
const GAME_PAGES: Record<string, MyGamesPage> = {
	'': { games: [game(12)], next: 12 },
	'12': {
		games: [game(11, { mode: 'multiplayer', placement: 3, final_score: -15, hand_count: 1 })],
		next: null
	}
};

interface ApiCalls {
	me: number;
	patches: unknown[];
	logouts: number;
	deletes: number;
	games: string[];
}

async function stubApi(
	page: Page,
	signedIn: boolean,
	gamePages: Record<string, MyGamesPage> = GAME_PAGES
): Promise<ApiCalls> {
	const calls: ApiCalls = { me: 0, patches: [], logouts: 0, deletes: 0, games: [] };
	await page.route(/\/me\/games(\?|$)/, (route) => {
		const before = new URL(route.request().url()).searchParams.get('before') ?? '';
		calls.games.push(before);
		return route.fulfill({ json: gamePages[before], headers: cors(route) });
	});
	let user: Me | null = signedIn ? { ...ANN } : null;
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route(`${API}/me`, async (route) => {
		const request = route.request();
		const headers = cors(route);
		if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
		if (request.method() === 'PATCH') {
			const body = request.postDataJSON();
			calls.patches.push(body);
			user = { ...user!, ...(body.display_name ? { display_name: body.display_name } : {}) };
			if (body.training_consent !== undefined) {
				user.training_consent_at = body.training_consent ? '2026-11-05T00:00:00Z' : null;
				user.consent_version = body.training_consent ? '2026-11-draft' : null;
			}
			return route.fulfill({ json: user, headers });
		}
		if (request.method() === 'DELETE') {
			calls.deletes++;
			user = null;
			return route.fulfill({ status: 204, headers });
		}
		calls.me++;
		return user
			? route.fulfill({ json: user, headers })
			: route.fulfill({ status: 401, json: { detail: 'not signed in' }, headers });
	});
	await page.route(`${API}/auth/logout`, (route) => {
		if (route.request().method() === 'POST') {
			calls.logouts++;
			user = null;
		}
		return route.fulfill({ status: 204, headers: cors(route) });
	});
	await page.route(`${API}/me/export`, (route) =>
		route.fulfill({ json: { user, identities: [], games: [] }, headers: cors(route) })
	);
	return calls;
}

// signed in: the lobby menu's account or games item opens its dialog
async function openFromMenu(page: Page, item: 'account' | 'games'): Promise<Locator> {
	await page.goto('/');
	await page.getByTestId('lobby-menu-button').click();
	await page.getByTestId(`lobby-menu-${item}`).click();
	const dialog = page.getByTestId(item === 'account' ? 'account-dialog' : 'my-games-dialog');
	await expect(dialog).toBeVisible();
	return dialog;
}

test.describe('accounts on', () => {
	test.use({ baseURL: ACCOUNTS });

	test('/profile now lands on the lobby', async ({ page }) => {
		await stubApi(page, true);
		await page.goto('/profile');
		await expect(page).toHaveURL(`${ACCOUNTS}/`);
		await expect(page.getByTestId('lobby-play-online')).toBeVisible();
	});

	test('a nameless guest is offered sign-in or a guest name on the lobby', async ({ page }) => {
		await stubApi(page, false);
		await page.goto('/');
		const dialog = page.getByTestId('welcome-dialog');
		await expect(dialog.getByTestId('google-sign-in')).toHaveAttribute(
			'href',
			`${API}/auth/google/login?next=%2F`
		);
		await expect(dialog.getByTestId('legal-links')).toBeVisible();
		await dialog.getByTestId('welcome-name').fill('Mei');
		await dialog.getByTestId('welcome-guest').click();
		await expect(dialog).toHaveCount(0);
	});

	test('a signed-in player is never asked for a guest name', async ({ page }) => {
		await stubApi(page, true);
		await page.goto('/');
		await expect(page.getByTestId('lobby-menu-button').locator('.avatar')).toHaveText('A');
		await expect(page.getByTestId('welcome-dialog')).toHaveCount(0);
	});

	test('a sign-in callback flag takes the lobby load instead of the welcome', async ({ page }) => {
		await stubApi(page, false);
		await page.goto('/?signin=failed');
		await expect(page.getByTestId('signin-error-dialog')).toBeVisible();
		await expect(page.getByTestId('welcome-dialog')).toHaveCount(0);
	});

	test('a guest signs in from the lobby menu', async ({ page }) => {
		await stubApi(page, false);
		await page.addInitScript(() =>
			localStorage.setItem('mahjong:displayName:v1', JSON.stringify('Mei'))
		);
		await page.goto('/');
		await page.getByTestId('lobby-menu-button').click();
		const menu = page.getByTestId('lobby-menu');
		await expect(menu.getByTestId('google-sign-in')).toHaveAttribute(
			'href',
			`${API}/auth/google/login?next=%2F`
		);
		await expect(menu.getByTestId('legal-links')).toBeVisible();
		await expect(menu.getByTestId('lobby-menu-sign-out')).toHaveCount(0);
	});

	test('the lobby menu signs a player out in place', async ({ page }) => {
		const calls = await stubApi(page, true);
		await page.goto('/');
		const trigger = page.getByTestId('lobby-menu-button');
		await expect(trigger.locator('.avatar')).toHaveText('A');
		await trigger.click();
		const menu = page.getByTestId('lobby-menu');
		await expect(menu.getByTestId('lobby-menu-name')).toHaveText('Ann');
		await menu.getByTestId('lobby-menu-sign-out').click();
		await expect(menu.getByTestId('google-sign-in')).toBeVisible();
		await expect(trigger.locator('.avatar')).toHaveCount(0);
		expect(calls.logouts).toBe(1);
	});

	test('a first sign-in confirms the name and asks for consent, unchecked', async ({ page }) => {
		const calls = await stubApi(page, true);
		await page.goto('/tables?signup=1');
		const dialog = page.getByTestId('signup-dialog');
		await expect(dialog).toBeVisible();
		await expect(page).toHaveURL(`${ACCOUNTS}/tables`);
		await expect(page.getByTestId('signup-name')).toHaveValue('Ann');
		const consent = page.getByTestId('training-consent').getByRole('checkbox');
		await expect(consent).not.toBeChecked();
		// opened in a new tab so the dialog survives
		await expect(dialog.getByTestId('legal-link-privacy')).toHaveAttribute('target', '_blank');
		await expect(dialog.getByTestId('legal-link-terms')).toHaveAttribute('href', '/terms');

		await page.getByTestId('signup-name').fill('Bea');
		await consent.check();
		await page.getByTestId('signup-submit').click();
		await expect(dialog).toBeHidden();
		expect(calls.patches).toEqual([{ display_name: 'Bea', training_consent: true }]);
	});

	test('a first sign-in suggests the guest name already used at tables', async ({ page }) => {
		await stubApi(page, true);
		await page.addInitScript(() =>
			localStorage.setItem('mahjong:displayName:v1', JSON.stringify('Bea'))
		);
		await page.goto('/tables?signup=1');
		await expect(page.getByTestId('signup-name')).toHaveValue('Bea');
	});

	test('the lobby menu opens the account dialog, which links the legal pages', async ({ page }) => {
		await stubApi(page, true);
		const dialog = await openFromMenu(page, 'account');
		await expect(dialog).toContainText('Ann');
		await expect(page).toHaveURL(`${ACCOUNTS}/`);
		await dialog.getByTestId('legal-link-privacy').click();
		await expect(page).toHaveURL(`${ACCOUNTS}/privacy`);
		await expect(page.getByTestId('privacy-page')).toBeVisible();
	});

	test('the account dialog closes on Escape, back to the menu button', async ({ page }) => {
		await stubApi(page, true);
		const dialog = await openFromMenu(page, 'account');
		await page.keyboard.press('Escape');
		await expect(dialog).toHaveCount(0);
		await expect(page.getByTestId('lobby-menu-button')).toBeFocused();
	});

	test('account settings rename and toggle consent', async ({ page }) => {
		const calls = await stubApi(page, true);
		const dialog = await openFromMenu(page, 'account');
		const save = page.getByTestId('account-name-save');
		await expect(save).toBeDisabled();
		await page.getByTestId('account-name').fill('Bea');
		await save.click();
		await expect(dialog.locator('.name')).toHaveText('Bea');
		await expect(page.getByTestId('lobby-menu-button').locator('.avatar')).toHaveText('B');

		const consent = page.getByTestId('training-consent').getByRole('checkbox');
		await consent.check();
		await expect(consent).toBeChecked();
		await consent.uncheck();
		await expect(consent).not.toBeChecked();
		expect(calls.patches).toEqual([
			{ display_name: 'Bea' },
			{ training_consent: true },
			{ training_consent: false }
		]);
	});

	test('export downloads the account json', async ({ page }) => {
		await stubApi(page, true);
		await openFromMenu(page, 'account');
		const [download] = await Promise.all([
			page.waitForEvent('download'),
			page.getByTestId('account-export').click()
		]);
		expect(download.suggestedFilename()).toBe('mahjong-account.json');
		const body = JSON.parse(await readFile(await download.path(), 'utf8'));
		expect(body.user.display_name).toBe('Ann');
	});

	// ?pregame=join freezes the seat picker without a socket (frontend-screenshots skill)
	test('a signed-in player joins under their account name, no name field', async ({ page }) => {
		await stubApi(page, true);
		await page.goto('/table/ABC123?pregame=join');
		await expect(page.getByTestId('pretable-playing-as')).toContainText('Ann');
		await expect(page.locator('#display-name-input')).toHaveCount(0);
	});

	test('a guest still types a name to join', async ({ page }) => {
		await stubApi(page, false);
		await page.goto('/table/ABC123?pregame=join');
		await expect(page.locator('#display-name-input')).toBeVisible();
		await expect(page.getByTestId('pretable-playing-as')).toHaveCount(0);
	});

	test('delete needs the typed name, then plays on as a guest', async ({ page }) => {
		const calls = await stubApi(page, true);
		const dialog = await openFromMenu(page, 'account');
		await page.getByTestId('account-delete').click();
		const submit = page.getByTestId('delete-account-submit');
		await expect(submit).toBeDisabled();
		await page.getByTestId('delete-account-confirm').fill('ann');
		await expect(submit).toBeDisabled();
		await page.getByTestId('delete-account-confirm').fill('Ann');
		await submit.click();
		await expect(page.getByTestId('delete-account-dialog')).toHaveCount(0);
		await expect(dialog).toHaveCount(0);
		await expect(page.getByTestId('lobby-menu-button').locator('.avatar')).toHaveCount(0);
		expect(calls.deletes).toBe(1);
	});

	test('my games list pages with load more, bots by their level', async ({ page }) => {
		const calls = await stubApi(page, true);
		const dialog = await openFromMenu(page, 'games');
		const rows = dialog.getByTestId('my-game');
		await expect(rows).toHaveCount(1);
		await expect(rows.first()).toContainText('1st');
		await expect(rows.first()).toContainText('+40');
		await expect(rows.first()).toContainText('Practice');
		await expect(rows.first()).toContainText('8 hands');
		await expect(rows.first()).toContainText('Expert');
		await expect(rows.first()).toContainText('Gone');
		await expect(rows.first()).toContainText('Guest');

		await page.getByTestId('my-games-more').click();
		await expect(rows).toHaveCount(2);
		await expect(rows.nth(1)).toContainText('3rd');
		await expect(rows.nth(1)).toContainText('-15');
		await expect(rows.nth(1)).toContainText('Multiplayer');
		await expect(rows.nth(1)).toContainText('1 hand');
		await expect(rows.nth(1)).not.toContainText('1 hands');
		await expect(page.getByTestId('my-games-more')).toHaveCount(0);
		expect(calls.games).toEqual(['', '12']);
	});

	test('my games shows an empty state', async ({ page }) => {
		await stubApi(page, true, { '': { games: [], next: null } });
		await openFromMenu(page, 'games');
		await expect(page.getByTestId('my-games-empty')).toBeVisible();
		await expect(page.getByTestId('my-games-more')).toHaveCount(0);
	});

	test('a guest has no account or games items, and no games are fetched', async ({ page }) => {
		const calls = await stubApi(page, false);
		await page.addInitScript(() =>
			localStorage.setItem('mahjong:displayName:v1', JSON.stringify('Mei'))
		);
		await page.goto('/');
		await page.getByTestId('lobby-menu-button').click();
		const menu = page.getByTestId('lobby-menu');
		await expect(menu.getByTestId('google-sign-in')).toBeVisible();
		await expect(menu.getByTestId('lobby-menu-account')).toHaveCount(0);
		await expect(menu.getByTestId('lobby-menu-games')).toHaveCount(0);
		expect(calls.games).toEqual([]);
	});

	// /learn skips the api gate, so its handler mounts during hydration
	for (const [flag, path] of [
		['failed', '/learn'],
		['disabled', '/']
	]) {
		test(`signin=${flag} on ${path} shows a message, url cleaned`, async ({ page }) => {
			await stubApi(page, false);
			await page.goto(`${path}?signin=${flag}`);
			const dialog = page.getByTestId('signin-error-dialog');
			await expect(dialog).toBeVisible();
			await expect(page).toHaveURL(`${ACCOUNTS}${path}`);
			await dialog.getByRole('button').click();
			await expect(dialog).toBeHidden();
		});
	}
});

test.describe('accounts off', () => {
	test('no /me request, no account ui, flags ignored', async ({ page }) => {
		const calls = await stubApi(page, true);
		await page.goto('/tables?signup=1');
		await expect(page.getByTestId('tables-header-create-table')).toBeVisible();
		await expect(page.getByTestId('signup-dialog')).toHaveCount(0);

		await page.goto('/');
		// a nameless guest still gets the welcome, name only
		const welcome = page.getByTestId('welcome-dialog');
		await expect(welcome).toBeVisible();
		await expect(welcome.getByTestId('google-sign-in')).toHaveCount(0);
		await welcome.getByTestId('welcome-later').click();
		await page.getByTestId('lobby-menu-button').click();
		const menu = page.getByTestId('lobby-menu');
		await expect(menu.getByTestId('lobby-settings')).toBeVisible();
		await expect(menu.getByTestId('account-panel')).toHaveCount(0);
		await expect(page.getByTestId('lobby-menu-button').locator('.avatar')).toHaveCount(0);
		expect(calls.me).toBe(0);
		expect(calls.games).toEqual([]);
	});
});
