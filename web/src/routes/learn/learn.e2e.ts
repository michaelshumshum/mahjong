import { expect, test, type Locator, type Page } from '@playwright/test';

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
	// the tutorial leads basics, then its 8 puzzles
	await expect(page.getByTestId('track-solved-basics')).toHaveText('0 / 9');
	await expect(page.getByTestId('track-basics').locator('.lesson-card').first()).toHaveAttribute(
		'data-testid',
		'lesson-card-basics-tutorial'
	);
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

test('a best discard puzzle shows every option, with the pick against the best', async ({
	page
}) => {
	await page.goto('/learn/basics-keep-two-sided');
	await discard(page, 4); // 2 Characters: ready, but fewer tiles than 5 Characters
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(feedback(page).locator('[data-line="discard-compare"]')).toContainText('7 unseen');
	const table = page.getByTestId('discard-table');
	await expect(table.locator('tr[data-picked="true"]')).toHaveAttribute('data-tile', '2m');
	await expect(table.locator('tr[data-answer="true"]')).toHaveAttribute('data-tile', '5m');
});

test("a safe discard that only luck made safe isn't solved", async ({ page }) => {
	await page.goto('/learn/defence-01');
	await discard(page, 12); // 4 Characters: nobody waits on it, but nothing shows that
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(feedback(page)).toHaveAttribute('data-lucky', 'true');
	await expect(feedback(page)).toContainText("couldn't have known");
	await expect(page.getByTestId('puzzle-solved')).toHaveCount(0);
	const table = page.getByTestId('safe-table');
	await expect(table.locator('tr[data-tile="z5"]')).toContainText('Deals in to North');

	await discard(page, 0); // 1 Characters: every copy visible
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await expect(feedback(page)).not.toHaveAttribute('data-lucky');
	await expect(feedback(page).locator('[data-line="why"]')).toContainText('every copy is visible');
	await expect(page.getByTestId('puzzle-solved')).toBeVisible();
});

test('a discard win: the claimed tile is marked, and the answer shows the faan breakdown', async ({
	page
}) => {
	await page.goto('/learn/basics-discard-win');
	await expect(page.getByTestId('held-discard')).toBeVisible();
	await expect(page.getByTestId('claimed-tile')).toBeVisible();

	await page.getByTestId('answer-faan').fill('5');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page).locator('[data-line="faan-high"]')).toBeVisible();
	await expect(page.getByTestId('faan-breakdown')).toHaveCount(0);

	await page.getByTestId('answer-faan').fill('4');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	const breakdown = page.getByTestId('faan-breakdown');
	await expect(breakdown.locator('.pattern-row')).toHaveCount(2);
	await expect(feedback(page).locator('[data-line="points"]')).toHaveText('Worth 16 points.');

	await breakdown.getByTestId('faan-pattern-link').first().click();
	const guide = page.getByTestId('guide-dialog');
	await expect(guide).toBeVisible();
	await expect(guide.locator('[data-pattern="混一色"]')).toBeFocused();
});

test('progress shows on the index and survives a reload', async ({ page }) => {
	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');

	await page.goto('/learn');
	await page.reload();
	await expect(page.getByTestId('track-solved-basics')).toHaveText('1 / 9');
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
	await page.getByTestId('lesson-previous').click();
	await expect(page).toHaveURL('/learn/basics-tutorial');
	await page.goto('/learn/basics-isolated-honour');
	await page.getByTestId('lesson-next').click();
	await expect(page).toHaveURL('/learn/basics-two-sided-wait');
	await expect(page.locator('h1')).toHaveText('A two-sided wait');
});

test('the index and a puzzle fit a phone without sideways scroll', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	for (const url of [
		'/learn',
		'/learn/basics-two-sided-wait',
		'/learn/basics-simple-hand',
		'/learn/basics-tutorial'
	]) {
		await page.goto(url);
		await expect(page.locator('h1')).toBeVisible();
		const overflow = await page.evaluate(
			() => document.documentElement.scrollWidth - document.documentElement.clientWidth
		);
		expect(overflow, url).toBe(0);
	}
});

test('puzzles answer by tap at phone width', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/learn/basics-isolated-honour');
	await discard(page, 124); // Red Dragon
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await expect(page.getByTestId('puzzle-solved')).toBeVisible();

	await page.goto('/learn/basics-two-sided-wait');
	await page.getByTestId('answer-tile-3m').click();
	await page.getByTestId('answer-tile-6m').click();
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
});

async function tabTo(page: Page, isTarget: () => Promise<boolean>): Promise<void> {
	for (let i = 0; i < 80 && !(await isTarget()); i++) await page.keyboard.press('Tab');
	expect(await isTarget()).toBe(true);
}

const focused = (locator: Locator) => () => locator.evaluate((el) => el === document.activeElement);

test('puzzles answer by keyboard alone', async ({ page }) => {
	await page.goto('/learn/basics-isolated-honour');
	await expect(page.getByTestId('table-scene')).toBeVisible();
	// the hand is one tab stop (roving tabindex); arrows move between its tiles.
	await tabTo(page, () =>
		page.evaluate(() => document.activeElement?.closest('.seat-region--self') !== null)
	);
	await page.keyboard.press('Home');
	const redDragon = page.locator('.seat-region--self [data-tile-id="124"]');
	for (let i = 0; i < 14 && !(await focused(redDragon)()); i++)
		await page.keyboard.press('ArrowRight');
	await page.keyboard.press('Enter');
	await page.keyboard.press('Enter');
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');

	await page.goto('/learn/basics-two-sided-wait');
	await tabTo(page, focused(page.getByTestId('answer-tile-3m')));
	await page.keyboard.press('Space');
	await tabTo(page, focused(page.getByTestId('answer-tile-6m')));
	await page.keyboard.press('Space');
	await tabTo(page, focused(page.getByTestId('answer-check')));
	await page.keyboard.press('Enter');
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
});

test('learn renders in zh-Hant', async ({ page, context, baseURL }) => {
	await context.addCookies([{ name: 'PARAGLIDE_LOCALE', value: 'zh-Hant', url: baseURL }]);
	await page.goto('/learn');
	await expect(page.locator('html')).toHaveAttribute('lang', 'zh-Hant');
	await expect(page.locator('h1')).toHaveText('學打牌');
	await expect(page).toHaveTitle('學打牌 · 開枱');

	await page.getByTestId('lesson-card-basics-isolated-honour').click();
	await expect(page.locator('h1')).toHaveText('打走孤張');
	await discard(page, 0); // 1 Characters
	await expect(feedback(page)).toContainText('未啱，再試一次。');
	await discard(page, 124); // Red Dragon
	await expect(feedback(page)).toContainText('答對了！');
	await expect(page.getByTestId('answer-explain')).toContainText('紅中');
});

const tip = (page: Page) => page.getByTestId('tutorial-tip');
const claimOverlay = (page: Page) => page.getByTestId('claim-overlay');

async function next(page: Page, tipText: string): Promise<void> {
	await expect(tip(page)).toContainText(tipText);
	await page.getByTestId('tutorial-next').click();
}

async function claim(page: Page, kind: 'pung' | 'chow' | 'kong'): Promise<void> {
	await claimOverlay(page).locator(`.claim-btn--${kind}`).click();
	await expect(claimOverlay(page)).toHaveCount(0);
}

test('the basics tutorial plays end to end by clicks', async ({ page }) => {
	await page.goto('/learn');
	const card = page.getByTestId('lesson-card-basics-tutorial');
	await expect(card).toContainText('Start here');
	await expect(card).toContainText('Your first hand');
	await card.click();
	await expect(page).toHaveURL('/learn/basics-tutorial');
	await expect(page.locator('h1')).toHaveText('Your first hand');
	await expect(page.getByTestId('tutorial-coach')).toContainText('Step 1 of 18');
	// the welcome tip points at the hub; no clock anywhere, so no timer ring
	await expect(page.locator('.table-surface')).toHaveAttribute('data-coach', 'hub');
	await expect(page.getByRole('timer')).toHaveCount(0);

	await next(page, 'Welcome to the table');
	await expect(page.locator('.table-surface')).toHaveAttribute('data-coach', 'hand');
	await next(page, 'These are your 13 tiles');
	await next(page, 'North discarded');

	// a wrong discard shows the hint and stays put
	await expect(tip(page)).toContainText('Discard the Green Dragon');
	await discard(page, 8); // 3 Characters
	await expect(page.getByTestId('tutorial-hint')).toBeVisible();
	await expect(tip(page)).toContainText('Discard the Green Dragon');
	await discard(page, 128); // Green Dragon

	await next(page, 'South discarded an East Wind');
	await expect(claimOverlay(page)).toBeVisible();
	await expect(claimOverlay(page).getByRole('timer')).toHaveCount(0);
	await claimOverlay(page).locator('.claim-btn--pass').click();
	await expect(claimOverlay(page).getByTestId('tutorial-hint')).toBeVisible();
	await claim(page, 'pung');
	await expect(page.locator('.seat-region--self .meld')).toHaveCount(1);

	await next(page, 'Your East pung is laid face up');
	await discard(page, 32); // 9 Characters
	await next(page, 'North, on your left, discarded the 4 Characters');
	await claim(page, 'chow');
	await expect(tip(page)).toContainText('Discard the Red Dragon');
	await discard(page, 124);
	await next(page, 'South discarded the 9 Dots');
	await claim(page, 'kong');
	await next(page, 'replacement tile');
	await discard(page, 132); // White Dragon
	await next(page, 'You drew the 2 Dots yourself');
	await page.locator('.declare-btn--hero').click();

	await expect(tip(page)).toContainText('The hand scores 4 faan');
	await expect(page.getByTestId('faan-breakdown').locator('.pattern-row')).toHaveCount(4);
	await expect(page.getByTestId('tutorial-solved')).toBeVisible();
	await page.getByTestId('tutorial-to-puzzles').click();
	await expect(page).toHaveURL('/learn');
	await expect(page.getByTestId('lesson-card-basics-tutorial')).toHaveAttribute(
		'data-solved',
		'true'
	);
});

test('the tutorial steps through its tips by keyboard alone', async ({ page }) => {
	await page.goto('/learn/basics-tutorial');
	const nextButton = page.getByTestId('tutorial-next');
	// the tip card's own button takes focus, and keeps it from tip to tip
	await expect(nextButton).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(tip(page)).toContainText('These are your 13 tiles');
	await expect(nextButton).toBeFocused();
	await page.keyboard.press('Enter');
	await expect(tip(page)).toContainText('North discarded');
	await expect(nextButton).toBeFocused();
	await page.keyboard.press('Enter');
	// a move on the table: focus lands on the tip, so the hand is the next tab stop
	await expect(tip(page)).toContainText('Discard the Green Dragon');
	await expect(tip(page)).toBeFocused();
	await tabTo(page, () =>
		page.evaluate(() => document.activeElement?.closest('.seat-region--self') !== null)
	);
	await page.keyboard.press('Home');
	const greenDragon = page.locator('.seat-region--self [data-tile-id="128"]');
	for (let i = 0; i < 14 && !(await focused(greenDragon)()); i++)
		await page.keyboard.press('ArrowRight');
	await page.keyboard.press('Enter');
	await page.keyboard.press('Enter');
	await expect(tip(page)).toContainText('South discarded an East Wind');
	await expect(nextButton).toBeFocused();
	await page.keyboard.press('Enter');
	// the claim dialog opens on Pass; its number keys claim
	await expect(claimOverlay(page)).toBeVisible();
	await page.keyboard.press('1');
	await expect(tip(page)).toContainText('Your East pung is laid face up');
});

test('the tutorial resumes where it was left after a reload', async ({ page }) => {
	await page.goto('/learn/basics-tutorial');
	await next(page, 'Welcome to the table');
	await next(page, 'These are your 13 tiles');
	await next(page, 'North discarded');
	await discard(page, 128);
	await expect(tip(page)).toContainText('South discarded an East Wind');

	await page.reload();
	const resume = page.getByTestId('tutorial-resume');
	await expect(resume).toContainText('step 5');
	await resume.getByTestId('tutorial-resume-button').click();
	await expect(tip(page)).toContainText('South discarded an East Wind');
	await expect(page.locator('.seat-region--self [data-tile-id="128"]')).toHaveCount(0);

	await page.getByTestId('tutorial-restart').click();
	await expect(tip(page)).toContainText('Welcome to the table');
	await page.reload();
	await expect(page.getByTestId('tutorial-resume')).toHaveCount(0);
});

test('an unknown lesson id is a 404', async ({ page }) => {
	await page.goto('/learn/no-such-lesson');
	await expect(page.locator('h1')).toHaveText('404');
});
