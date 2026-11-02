import { expect, test, type Locator, type Page } from '@playwright/test';

// learn ships its lessons as static JSON: with /healthz unreachable, nothing here may wait on it.
test.beforeEach(async ({ page }) => {
	await page.route('**/healthz', (route) => route.abort());
});

const handTile = (page: Page, tileId: number) =>
	page.locator(`.seat-region--self [data-tile-id="${tileId}"]`);

// puzzles are always two-step: the first tap picks the tile, the second grades it.
async function discard(page: Page, tileId: number): Promise<void> {
	await handTile(page, tileId).click();
	await handTile(page, tileId).click();
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
	// mined puzzles are titled by what they teach
	await expect(page.getByTestId('lesson-card-waits-01')).toContainText('Two-sided wait');
	await expect(page.getByTestId('track-waits')).toContainText(
		'Find every tile that completes the hand.'
	);
	// cards sit under band headings, in band order
	const headings = page.getByTestId('track-waits').locator('.band-heading');
	await expect(headings).toHaveText(['Beginner', 'Intermediate', 'Advanced']);
	// "Puzzle N" only where a band holds the theme twice
	await expect(page.getByTestId('lesson-sub-waits-01')).toHaveText('Puzzle 1');
	await expect(page.getByTestId('lesson-sub-waits-03')).toHaveCount(0);
	// endless (the one part needing the server) comes after the last track
	const order = await page.evaluate(() =>
		[...document.querySelectorAll('[data-testid^="track-"], [data-testid="endless"]')]
			.filter((el) => el.tagName === 'SECTION')
			.map((el) => el.getAttribute('data-testid'))
	);
	expect(order.at(-1)).toBe('endless');
	expect(order.at(-2)).toBe('track-faan');
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

test('a discard puzzle: pick a tile, then Check grades it', async ({ page }) => {
	await page.goto('/learn/basics-isolated-honour');
	const check = page.getByTestId('answer-check');
	await expect(check).toBeDisabled();
	await handTile(page, 0).click(); // 1 Characters
	await expect(handTile(page, 0)).toHaveClass(/hand-tile--lifted/);
	await expect(feedback(page)).not.toHaveAttribute('data-result');
	await check.click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(check).toBeDisabled();
	// the pick is marked on the table; the answer isn't, until it's asked for
	await expect(handTile(page, 0)).toHaveAttribute('data-mark', 'pick');
	await expect(page.locator('.seat-region--self [data-mark="answer"]')).toHaveCount(0);

	await handTile(page, 124).click(); // Red Dragon
	await check.click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await expect(handTile(page, 124)).toHaveAttribute('data-mark', 'answer');
});

test('a best discard puzzle hints at a miss, and shows every option once revealed', async ({
	page
}) => {
	await page.goto('/learn/basics-keep-two-sided');
	await discard(page, 4); // 2 Characters: ready, but fewer tiles than 5 Characters
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(feedback(page).locator('[data-line="discard-compare"]')).toContainText('7 unseen');
	await expect(page.getByTestId('discard-table')).toHaveCount(0);
	await expect(page.getByTestId('answer-next')).toHaveCount(0);

	await page.getByTestId('answer-reveal').click();
	await expect(page.getByTestId('answer-reveal')).toHaveCount(0);
	await expect(feedback(page)).toHaveAttribute('data-revealed', 'true');
	await expect(page.getByTestId('answer-explain')).toBeVisible();
	const table = page.getByTestId('discard-table');
	await expect(table.locator('tr[data-picked="true"]')).toHaveAttribute('data-tile', '2m');
	await expect(table.locator('tr[data-answer="true"]')).toHaveAttribute('data-tile', '5m');
	await expect(handTile(page, 4)).toHaveAttribute('data-mark', 'pick');
	await expect(page.locator('.seat-region--self [data-mark="answer"]')).not.toHaveCount(0);
	// seeing the answer doesn't solve it
	await expect(page.getByTestId('puzzle-solved')).toHaveCount(0);
	await expect(page.getByTestId('answer-next')).toBeVisible();
});

test("a safe discard that only luck made safe isn't solved", async ({ page }) => {
	await page.goto('/learn/defence-02');
	await discard(page, 4); // 2 Characters: nobody waits on it, but nothing shows that
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(feedback(page)).toHaveAttribute('data-lucky', 'true');
	await expect(feedback(page)).toContainText("couldn't have known");
	await expect(page.getByTestId('puzzle-solved')).toHaveCount(0);
	await expect(page.getByTestId('safe-table')).toHaveCount(0);
	await page.getByTestId('answer-reveal').click();
	const table = page.getByTestId('safe-table');
	await expect(table.locator('tr[data-tile="z5"]')).toContainText('Deals in to East');
	await expect(page.getByTestId('puzzle-solved')).toHaveCount(0);

	// still answerable after the reveal
	await discard(page, 100); // 8 Bamboo: every copy visible
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
	await expect(page.getByTestId('track-bar-basics')).toHaveAttribute('aria-valuenow', '1');
	await expect(page.getByTestId('track-bar-basics')).toHaveAttribute('aria-valuemax', '9');
	// the unsolved tutorial stays the lead card
	await expect(page.getByTestId('learn-continue')).toHaveCount(0);
	await expect(page.getByTestId('lesson-card-basics-tutorial')).toContainText('Start here');
});

async function seedProgress(page: Page, ids: readonly string[]): Promise<void> {
	await page.addInitScript((ids) => {
		const progress = Object.fromEntries(ids.map((id) => [id, { solved: true, attempts: 1 }]));
		localStorage.setItem('mahjong:learnProgress:v1', JSON.stringify(progress));
	}, ids);
}

test('once the tutorial is solved, a continue card leads to the first unsolved lesson', async ({
	page
}) => {
	await seedProgress(page, ['basics-tutorial']);
	await page.goto('/learn');
	const card = page.getByTestId('learn-continue');
	await expect(card).toContainText('Basics · Discard the loner');
	await card.click();
	await expect(page).toHaveURL('/learn/basics-isolated-honour');
});

test('the continue card crosses tracks, and gives way to a note once all are solved', async ({
	page
}) => {
	const basics = [
		'basics-tutorial',
		'basics-isolated-honour',
		'basics-two-sided-wait',
		'basics-keep-two-sided',
		'basics-pair-wait',
		'basics-simple-hand',
		'basics-discard-win',
		'basics-all-copies-visible',
		'basics-no-chance'
	];
	await seedProgress(page, basics);
	await page.goto('/learn');
	await expect(page.getByTestId('learn-continue')).toContainText('Waits · Two-sided wait');
	await expect(page.getByTestId('learn-continue')).toHaveAttribute('href', '/learn/waits-01');
	await expect(page.getByTestId('lesson-card-basics-tutorial')).not.toContainText('Start here');

	const all = await page.evaluate(() =>
		[...document.querySelectorAll('[data-testid^="lesson-card-"]')].map((el) =>
			el.getAttribute('data-testid')!.slice('lesson-card-'.length)
		)
	);
	await seedProgress(page, all);
	await page.goto('/learn');
	await expect(page.getByTestId('learn-continue')).toHaveCount(0);
	await expect(page.getByTestId('learn-all-solved')).toBeVisible();
	await page.getByTestId('learn-all-solved').getByRole('link').click();
	await expect(page.getByTestId('endless')).toBeInViewport();
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

test('a puzzle shows its place in the track, the tutorial counted', async ({ page }) => {
	await page.goto('/learn/basics-isolated-honour');
	await expect(page.getByTestId('puzzle-position')).toHaveText('Basics · 2 / 9');
	await page.goto('/learn/waits-01');
	await expect(page.getByTestId('puzzle-position')).toHaveText('Waits · 1 / 15');
});

test('next after an answer skips solved lessons, wraps round, then leads home', async ({
	page
}) => {
	await seedProgress(page, ['basics-two-sided-wait', 'basics-keep-two-sided']);
	await page.goto('/learn/basics-isolated-honour');
	await discard(page, 124); // Red Dragon
	await expect(page.getByTestId('answer-next')).toHaveAttribute('href', '/learn/basics-pair-wait');
	// the nav's Next stays the plain next lesson
	await expect(page.getByTestId('lesson-next')).toHaveAttribute(
		'href',
		'/learn/basics-two-sided-wait'
	);

	await page.goto('/learn');
	const all = await page.evaluate(() =>
		[...document.querySelectorAll('[data-testid^="lesson-card-"]')].map((el) =>
			el.getAttribute('data-testid')!.slice('lesson-card-'.length)
		)
	);
	// only the tutorial, earlier in the order, is left
	await seedProgress(
		page,
		all.filter((id) => id !== 'basics-tutorial')
	);
	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	await expect(page.getByTestId('answer-next')).toHaveAttribute('href', '/learn/basics-tutorial');

	await seedProgress(page, all);
	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	const next = page.getByTestId('answer-next');
	await expect(next).toHaveAttribute('href', '/learn');
	await expect(next).toHaveText('Back to all puzzles');
});

test('enter checks a pending pick and N moves on, but not while typing', async ({ page }) => {
	await page.goto('/learn/basics-isolated-honour');
	await handTile(page, 124).click(); // Red Dragon
	// focus off the hand, as after a click in Safari, which doesn't focus buttons
	await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
	await page.keyboard.press('Enter');
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await expect(page.getByTestId('next-key-hint')).toHaveText('Press N for next');
	await page.keyboard.press('n');
	await expect(page).toHaveURL('/learn/basics-two-sided-wait');

	await page.goto('/learn/basics-simple-hand');
	await page.getByTestId('answer-faan').fill('3');
	await page.getByTestId('answer-check').click();
	await expect(feedback(page)).toHaveAttribute('data-result', 'correct');
	await page.getByTestId('answer-faan').press('n');
	await expect(page).toHaveURL('/learn/basics-simple-hand');
	// nor with the guide dialog open
	await page.getByTestId('faan-pattern-link').first().click();
	await expect(page.getByTestId('guide-dialog')).toBeVisible();
	await page.keyboard.press('n');
	await expect(page).toHaveURL('/learn/basics-simple-hand');
});

test('opponents fade where the puzzle has no use for them', async ({ page }) => {
	const opacity = (locator: Locator) => locator.evaluate((el) => getComputedStyle(el).opacity);
	const across = (page: Page) => page.locator('.seat-region--across .seat-plate');
	const acrossPool = (page: Page) => page.locator('.discard-pool--across');

	// waits read visible tiles (dead waits), so only plates and hidden hands fade
	await page.goto('/learn/basics-isolated-honour');
	await expect(page.getByTestId('table-scene')).toHaveAttribute('data-dim-opponents', 'hands');
	expect(await opacity(across(page))).toBe('0.55');
	expect(await opacity(acrossPool(page))).toBe('1');

	// defence reads every discard
	await page.goto('/learn/defence-02');
	await expect(page.getByTestId('table-scene')).not.toHaveAttribute('data-dim-opponents');
	expect(await opacity(across(page))).toBe('1');

	// count faan fades their discards too, but not the pool holding the claimed tile
	await page.goto('/learn/basics-discard-win');
	await expect(page.getByTestId('table-scene')).toHaveAttribute('data-dim-opponents', 'all');
	const held = page.locator('.discard-pool:has([data-testid="held-discard"])');
	expect(await opacity(held)).toBe('1');
	const others = page.locator(
		'.discard-pool:not(.discard-pool--self):not(:has([data-testid="held-discard"]))'
	);
	expect(await opacity(others.first())).toBe('0.55');
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
	// the answer card sits under the table here: the result scrolls into view
	await expect(feedback(page)).toBeInViewport();
});

test('a graded discard at phone width scrolls its result into view', async ({ page }) => {
	await page.setViewportSize({ width: 390, height: 844 });
	await page.goto('/learn/basics-isolated-honour');
	await expect(feedback(page)).not.toBeInViewport();
	await discard(page, 0); // 1 Characters
	await expect(feedback(page)).toHaveAttribute('data-result', 'wrong');
	await expect(feedback(page)).toBeInViewport();
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
	await expect(page.getByTestId('lesson-card-waits-01')).toContainText('兩頭聽');

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

test('finishing the tutorial ends the coach marks and offers practice vs easy bots', async ({
	page
}) => {
	let sentBody: Record<string, unknown> | null = null;
	await page.route('**/tables', (route) => {
		if (route.request().method() !== 'POST') return route.fallback();
		sentBody = route.request().postDataJSON();
		return route.fulfill({
			json: { table_id: 'EASY01', ruleset_preset: 'hk_classic', ruleset: {} }
		});
	});
	// straight to the win through the saved resume point
	await page.goto('/learn/basics-tutorial');
	await page.evaluate(() =>
		localStorage.setItem(
			'mahjong:learnProgress:v1',
			JSON.stringify({ 'basics-tutorial': { solved: false, attempts: 0, step: 25 } })
		)
	);
	await page.reload();
	await page.getByTestId('tutorial-resume-button').click();
	await expect(tip(page)).toContainText('Declare the win');
	await page.locator('.declare-btn--hero').click();
	await expect(page.getByTestId('tutorial-to-puzzles')).toBeVisible();
	expect(
		await page.evaluate(() => JSON.parse(localStorage.getItem('mahjong:onboarding:v1') ?? 'null'))
	).toEqual({ coachMarksDone: true });

	await page.getByTestId('tutorial-practice').click();
	await expect(page).toHaveURL('/table/EASY01?practice=1');
	expect(sentBody).toEqual({ practice: true, bot_tiers: { 1: 'T1', 2: 'T1', 3: 'T1' } });
	expect(
		await page.evaluate(() =>
			JSON.parse(localStorage.getItem('mahjong:practiceSetup:v1') ?? 'null')
		)
	).toEqual({ 1: 'easy', 2: 'easy', 3: 'easy' });
});

test('an unknown lesson id is a 404', async ({ page }) => {
	await page.goto('/learn/no-such-lesson');
	await expect(page.locator('h1')).toHaveText('404');
});
