import { expect, test, type Page, type Route } from '@playwright/test';
import { ACCOUNTS_PORT } from '../../../playwright.config';
import type { Me } from '../../lib/net/account';
import type { LearnImportWire, LearnWire } from '../../lib/net/learn-api';

// learn progress for a signed-in player against a stubbed api (ADR 0028 phase 5)
const ACCOUNTS = `http://localhost:${ACCOUNTS_PORT}`;
const API = 'http://localhost:8000';
const PROGRESS_KEY = 'mahjong:learnProgress:v1';
const ENDLESS_KEY = 'mahjong:learnEndless:v1';
const PUZZLE = 'basics-isolated-honour';
const ANN: Me = {
	id: '00000000-0000-0000-0000-000000000001',
	display_name: 'Ann',
	created_at: '2026-11-01T00:00:00Z',
	training_consent_at: null,
	consent_version: null
};

test.use({ baseURL: ACCOUNTS });

function cors(route: Route): Record<string, string> {
	return {
		'Access-Control-Allow-Origin': route.request().headers()['origin'] ?? ACCOUNTS,
		'Access-Control-Allow-Credentials': 'true',
		'Access-Control-Allow-Methods': 'GET, POST, PUT, PATCH, DELETE',
		'Access-Control-Allow-Headers': 'Content-Type'
	};
}

interface Calls {
	imports: LearnImportWire[];
	puts: { url: string; body: unknown }[];
	patches: unknown[];
}

async function stubApi(page: Page, { importStatus = 200 } = {}): Promise<Calls> {
	const calls: Calls = { imports: [], puts: [], patches: [] };
	let learn: LearnWire = { progress: {}, endless: {}, prefs: {} };
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
	await page.route(`${API}/me`, (route) => {
		const request = route.request();
		const headers = cors(route);
		if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
		if (request.method() === 'PATCH') calls.patches.push(request.postDataJSON());
		return route.fulfill({ json: ANN, headers });
	});
	await page.route(`${API}/me/learn**`, (route) => {
		const request = route.request();
		const headers = cors(route);
		if (request.method() === 'OPTIONS') return route.fulfill({ status: 204, headers });
		if (request.method() === 'PUT') {
			calls.puts.push({ url: request.url(), body: request.postDataJSON() });
			return route.fulfill({ json: {}, headers });
		}
		if (request.method() === 'POST') {
			calls.imports.push(request.postDataJSON());
			if (importStatus !== 200) return route.fulfill({ status: importStatus, headers });
			learn = {
				...learn,
				progress: { [PUZZLE]: { solved: true, attempts: 1, imported: true } }
			};
			return route.fulfill({ json: { ...learn, dropped: 0 }, headers });
		}
		return route.fulfill({ json: learn, headers });
	});
	return calls;
}

async function seedGuestProgress(page: Page): Promise<void> {
	await page.goto('/learn');
	await page.evaluate(
		([progressKey, endlessKey, id]) => {
			localStorage.setItem(progressKey, JSON.stringify({ [id]: { solved: true, attempts: 1 } }));
			localStorage.setItem(endlessKey, JSON.stringify({ band: 'advanced', scores: {} }));
		},
		[PROGRESS_KEY, ENDLESS_KEY, PUZZLE]
	);
	await page.reload();
}

const stored = (page: Page, key: string) => page.evaluate((k) => localStorage.getItem(k), key);

test('a signed-in player uploads guest progress once, then the keys are gone', async ({ page }) => {
	const calls = await stubApi(page);
	await seedGuestProgress(page);
	const offer = page.getByTestId('learn-upload-offer');
	await expect(offer).toBeVisible();
	// the account's own progress shows until the upload
	await expect(page.getByTestId('learn-tab-count-basics')).toHaveText('0 / 9');
	await page.getByTestId('learn-upload-accept').click();
	await expect(offer).toHaveCount(0);
	expect(calls.imports).toEqual([
		{
			progress: { [PUZZLE]: { solved: true, attempts: 1, solved_at: null, step: null } },
			endless: {},
			prefs: { learn_band: 'advanced' }
		}
	]);
	expect(await stored(page, PROGRESS_KEY)).toBeNull();
	expect(await stored(page, ENDLESS_KEY)).toBeNull();
	await expect(page.getByTestId('learn-tab-count-basics')).toHaveText('1 / 9');
	await page.reload();
	await expect(page.getByTestId('learn-tab-count-basics')).toHaveText('1 / 9');
	await expect(offer).toHaveCount(0);
});

test('a failed upload keeps the keys and says so', async ({ page }) => {
	const calls = await stubApi(page, { importStatus: 500 });
	await seedGuestProgress(page);
	await page.getByTestId('learn-upload-accept').click();
	await expect(page.getByTestId('learn-upload-offer').getByRole('alert')).toBeVisible();
	expect(calls.imports).toHaveLength(1);
	expect(await stored(page, PROGRESS_KEY)).not.toBeNull();
	expect(await stored(page, ENDLESS_KEY)).not.toBeNull();
});

test('not now hides the offer and keeps the keys', async ({ page }) => {
	const calls = await stubApi(page);
	await seedGuestProgress(page);
	await page.getByRole('button', { name: 'Not now' }).click();
	await expect(page.getByTestId('learn-upload-offer')).toHaveCount(0);
	await page.reload();
	await expect(page.getByTestId('learn-tab-count-basics')).toHaveText('0 / 9');
	await expect(page.getByTestId('learn-upload-offer')).toHaveCount(0);
	expect(calls.imports).toEqual([]);
	expect(await stored(page, PROGRESS_KEY)).not.toBeNull();
});

test('a signed-in band pick goes to the account, not localStorage', async ({ page }) => {
	const calls = await stubApi(page);
	const learnLoaded = page.waitForResponse(`${API}/me/learn`);
	await page.goto('/learn?track=endless');
	await learnLoaded;
	await expect(page.getByTestId('endless')).toBeVisible();
	const advanced = page.getByTestId('endless-band').getByRole('radio', { name: 'Advanced' });
	await advanced.check();
	await expect.poll(() => calls.patches).toEqual([{ prefs: { learn_band: 'advanced' } }]);
	expect(await stored(page, ENDLESS_KEY)).toBeNull();
});
