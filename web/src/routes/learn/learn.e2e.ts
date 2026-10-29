import { expect, test, type Page } from '@playwright/test';

// learn ships its lessons as static JSON: with /healthz unreachable, nothing here may wait on it.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.abort());
});

// default discard mode is two-step: the first tap lifts the tile, the second discards it.
async function discard(page: Page, tileId: number): Promise<void> {
	const tile = page.locator(`.seat-region--self [data-tile-id="${tileId}"]`);
	await tile.click();
	await tile.click();
}

const feedback = (page: Page) => page.getByTestId('answer-feedback');

test('the index lists every track and its lessons', async ({ page }) => {
	await page.goto('/learn');
	await expect(page.locator('h1')).toHaveText('Learn');
	for (const track of ['basics', 'waits', 'efficiency', 'defence', 'faan']) {
		await expect(page.getByTestId(`track-${track}`)).toBeVisible();
	}
	await expect(page.getByTestId('track-solved-basics')).toHaveText('0 / 8');
	await expect(page.getByTestId('track-waits').locator('.lesson-card')).toHaveCount(15);
	await expect(page.getByTestId('lesson-card-basics-isolated-honour')).toContainText(
		'Discard the loner'
	);
	await expect(page.getByTestId('lesson-card-waits-01')).toContainText('Waits 1');
});

test('a best discard puzzle: a wrong tile says try again, the right one solves it', async ({
	page
}) => {
	await page.goto('/learn');
	await page.getByTestId('lesson-card-basics-isolated-honour').click();
	await expect(page).toHaveURL('/learn/basics-isolated-honour');
	await expect(page.locator('h1')).toHaveText('Discard the loner');
	await expect(page.getByTestId('table-scene')).toBeVisible();

	await discard(page, 0); // 1 Characters
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(page.getByTestId('answer-explain')).toHaveCount(0);

	await discard(page, 124); // Red Dragon
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await expect(page.getByTestId('answer-explain')).toContainText('Red Dragon');
	await expect(page.getByTestId('puzzle-solved')).toBeVisible();
	await page.getByTestId('answer-next').click();
	await expect(page).toHaveURL('/learn/basics-two-sided-wait');
});

test('a winning tiles puzzle: a partial pick, then the full set', async ({ page }) => {
	await page.goto('/learn/basics-two-sided-wait');
	await page.getByTestId('answer-tile-3m').click();
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'partial');
	await page.getByTestId('answer-tile-6m').click();
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
});

test('a count faan puzzle takes a number', async ({ page }) => {
	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('4');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
});

test('progress shows on the index and survives a reload', async ({ page }) => {
	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');

	await page.goto('/learn');
	await page.reload();
	await expect(page.getByTestId('track-solved-basics')).toHaveText('1 / 8');
	await expect(page.getByTestId('lesson-card-basics-simple-hand')).toHaveAttribute(
		'data-solved',
		'true'
	);
	await expect(page.getByTestId('lesson-card-basics-isolated-honour')).toHaveAttribute(
		'data-solved',
		'false'
	);
});

test('prev and next walk the index', async ({ page }) => {
	await page.goto('/learn/basics-two-sided-wait');
	await page.getByTestId('lesson-previous').click();
	await expect(page).toHaveURL('/learn/basics-isolated-honour');
	await expect(page.getByTestId('lesson-previous')).toHaveCount(0);
	await page.getByTestId('lesson-next').click();
	await expect(page).toHaveURL('/learn/basics-two-sided-wait');
	await expect(page.locator('h1')).toHaveText('A two-sided wait');
});

test('the index and a puzzle fit a phone without sideways scroll', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	for (const url of ['/learn', '/learn/basics-two-sided-wait', '/learn/basics-simple-hand']) {
		await page.goto(url);
		await expect(page.locator('h1')).toBeVisible();
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(overflow, url).toBe(0);
	}
});

test('an unknown lesson id is a 404', async ({ page }) => {
	await page.goto('/learn/no-such-lesson');
	await expect(page.locator('h1')).toHaveText('404');
});
