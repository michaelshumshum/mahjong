import { expect, test, type Page, type Route } from '@playwright/test';
import first from '../../../lib/learn/generated/basics-isolated-honour.json' with { type: 'json' };
import second from '../../../lib/learn/generated/basics-keep-two-sided.json' with { type: 'json' };
import mined from '../../../lib/learn/generated/efficiency-01.json' with { type: 'json' };

// unlike curated lessons, endless puzzles come from GET /lessons/random, behind the api gate.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.fulfill({ json: { status: 'ok' } }));
});

const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Expose-Headers': 'Retry-After' };

/** Serves `responses` in order, one per request, recording each request's url. */
async function serve(page: Page, responses: ((route: Route) => Promise<void>)[]): Promise<URL[]> {
	const seen: URL[] = [];
	await page.route('**/lessons/random**', (route) => {
		seen.push(new URL(route.request().url()));
		const respond = responses[Math.min(seen.length, responses.length) - 1];
		return respond(route);
	});
	return seen;
}

const lesson = (body: unknown) => (route: Route) => route.fulfill({ json: body, headers: CORS });
const status =
	(code: number, headers: Record<string, string> = {}) =>
	(route: Route) =>
		route.fulfill({ status: code, json: { detail: 'x' }, headers: { ...CORS, ...headers } });

async function discard(page: Page, tileId: number): Promise<void> {
	const tile = page.locator(`.seat-region--self [data-tile-id="${tileId}"]`);
	await tile.click();
	await tile.click();
}

const streak = (page: Page) => page.getByTestId('endless-streak');

test('the index links each kind to endless mode at the picked band', async ({ page }) => {
	await page.route('**/healthz', (route) => route.abort());
	await page.goto('/learn');
	const card = page.getByTestId('endless-card-best_discard');
	await expect(card).toHaveAttribute('href', '/learn/endless?kind=best_discard&band=beginner');
	const advanced = page.getByTestId('endless-band').getByRole('radio', { name: 'Advanced' });
	await advanced.check();
	await expect(card).toHaveAttribute('href', '/learn/endless?kind=best_discard&band=advanced');
	await page.reload();
	await expect(advanced).toBeChecked();
});

test('answer right, the streak counts it, and the next puzzle loads without repeating', async ({
	page
}) => {
	const seen = await serve(page, [lesson(first), lesson(second), lesson(mined)]);
	await page.goto('/learn/endless?kind=best_discard&band=beginner');
	const puzzle = page.getByTestId('puzzle-page');
	await expect(puzzle).toHaveAttribute('data-lesson', 'basics-isolated-honour');
	await expect(page.locator('h1')).toHaveText('Discard the loner');
	await expect(streak(page)).toHaveAttribute('data-streak', '0');
	expect(seen[0].searchParams.get('kind')).toBe('best_discard');
	expect(seen[0].searchParams.get('band')).toBe('beginner');

	await discard(page, 124); // Red Dragon
	await expect(page.getByTestId('answer-feedback')).toHaveAttribute('data-result', 'correct');
	await expect(streak(page)).toHaveAttribute('data-streak', '1');

	await page.getByTestId('endless-next').click();
	await expect(puzzle).toHaveAttribute('data-lesson', 'basics-keep-two-sided');
	expect(seen[1].searchParams.getAll('exclude')).toEqual(['basics-isolated-honour']);
	await expect(streak(page)).toHaveAttribute('data-streak', '1');

	// 2 Characters: ready, but not the best
	await discard(page, 4);
	await expect(page.getByTestId('answer-feedback')).toHaveAttribute('data-result', 'wrong');
	await expect(streak(page)).toHaveAttribute('data-streak', '0');

	// a mined puzzle is titled by its theme, as on its own page
	await page.getByTestId('endless-skip').click();
	await expect(puzzle).toHaveAttribute('data-lesson', 'efficiency-01');
	await expect(page.locator('h1')).toHaveText('Discard to be ready');

	await page.goto('/learn');
	await expect(page.getByTestId('endless-best-best_discard')).toContainText('Best: 1');
});

test('a failed fetch says so and retries', async ({ page }) => {
	await serve(page, [status(503), lesson(first)]);
	await page.goto('/learn/endless?kind=best_discard');
	const error = page.getByTestId('endless-error');
	await expect(error).toHaveAttribute('data-error', 'unavailable');
	await expect(error).toContainText("Couldn't load a puzzle");
	await page.getByTestId('endless-retry').click();
	await expect(page.getByTestId('puzzle-page')).toHaveAttribute(
		'data-lesson',
		'basics-isolated-honour'
	);
});

test('a rate-limited fetch names the wait', async ({ page }) => {
	await serve(page, [status(429, { 'Retry-After': '30' })]);
	await page.goto('/learn/endless?kind=best_discard');
	const error = page.getByTestId('endless-error');
	await expect(error).toHaveAttribute('data-error', 'rate_limited');
	await expect(error).toContainText('Try again in 30 s');
});

test('an unknown kind is a 404', async ({ page }) => {
	await page.goto('/learn/endless?kind=claim');
	await expect(page.getByText('Page not found')).toBeVisible();
});
