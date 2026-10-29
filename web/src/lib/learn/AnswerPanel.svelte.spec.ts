import { flushSync } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanupAll, render } from '$lib/table/test-render';
import defence01 from './generated/defence-01.json';
import efficiency01 from './generated/efficiency-01.json';
import faan02 from './generated/faan-02.json';
import isolatedHonour from './generated/basics-isolated-honour.json';
import keepTwoSided from './generated/basics-keep-two-sided.json';
import simpleHand from './generated/basics-simple-hand.json';
import twoSidedWait from './generated/basics-two-sided-wait.json';
import waits12 from './generated/waits-12.json';
import type { Lesson } from './generated/lessons';
import { grade } from './grade';
import { puzzleState } from './puzzle-state';
import type { Answer } from './types';
import AnswerPanel from './AnswerPanel.svelte';

afterEach(cleanupAll);

function props(lesson: unknown, extra: Record<string, unknown> = {}) {
	return {
		lesson: lesson as Lesson,
		discardMode: 'two-step' as const,
		answer: null,
		result: null,
		attempts: 0,
		explanation: 'because',
		seatNames: puzzleState(lesson as Lesson).names,
		onAnswer: vi.fn(),
		...extra
	};
}

// the panel as the page shows it after grading `answer`
function answered(lesson: unknown, answer: Answer, extra: Record<string, unknown> = {}) {
	const result = grade(lesson as Lesson, answer).result;
	return render(AnswerPanel, props(lesson, { answer, result, attempts: 1, ...extra })).target;
}

function byTestId<T extends HTMLElement>(target: HTMLElement, id: string): T {
	return target.querySelector<T>(`[data-testid="${id}"]`)!;
}

function lines(target: HTMLElement): Record<string, string[]> {
	const out: Record<string, string[]> = {};
	for (const li of target.querySelectorAll<HTMLElement>('[data-testid="feedback-line"]')) {
		(out[li.dataset.line!] ??= []).push(li.textContent!.trim());
	}
	return out;
}

function rows(target: HTMLElement, table: string) {
	return [...byTestId(target, table).querySelectorAll<HTMLTableRowElement>('tbody tr')].map(
		(tr) => ({
			tile: tr.dataset.tile,
			answer: tr.dataset.answer === 'true',
			picked: tr.dataset.picked === 'true',
			cells: [...tr.querySelectorAll('td')].map((td) => td.textContent!.trim())
		})
	);
}

describe('AnswerPanel', () => {
	it('discard kinds show only the tap hint: the hand on the table is the input', () => {
		const { target } = render(AnswerPanel, props(isolatedHonour));
		expect(target.querySelector('button')).toBeNull();
		expect(target.querySelector('.hint')).not.toBeNull();
	});

	it('winning_tiles sends the picked tiles on Check', () => {
		const p = props(twoSidedWait);
		const { target } = render(AnswerPanel, p);
		const check = byTestId<HTMLButtonElement>(target, 'answer-check');
		expect(check.disabled).toBe(true);
		byTestId<HTMLButtonElement>(target, 'answer-tile-3m').click();
		byTestId<HTMLButtonElement>(target, 'answer-tile-6m').click();
		byTestId<HTMLButtonElement>(target, 'answer-tile-9m').click();
		byTestId<HTMLButtonElement>(target, 'answer-tile-9m').click();
		flushSync();
		expect(byTestId(target, 'answer-tile-3m').getAttribute('aria-pressed')).toBe('true');
		check.click();
		expect(p.onAnswer).toHaveBeenCalledWith({ kind: 'winning_tiles', tiles: ['3m', '6m'] });
	});

	it('count_faan sends the entered number on Check', () => {
		const p = props(simpleHand);
		const { target } = render(AnswerPanel, p);
		const input = byTestId<HTMLInputElement>(target, 'answer-faan');
		input.value = '3';
		input.dispatchEvent(new Event('input', { bubbles: true }));
		flushSync();
		byTestId<HTMLButtonElement>(target, 'answer-check').click();
		expect(p.onAnswer).toHaveBeenCalledWith({ kind: 'count_faan', faan: 3 });
	});

	it('shows the explanation only once the answer is correct', () => {
		const wrong = answered(simpleHand, { kind: 'count_faan', faan: 2 });
		expect(byTestId(wrong, 'answer-feedback').dataset.result).toBe('wrong');
		expect(byTestId(wrong, 'answer-explain')).toBeNull();
		const right = answered(simpleHand, { kind: 'count_faan', faan: 3 });
		expect(byTestId(right, 'answer-explain').textContent).toBe('because');
	});

	it('keeps the tables out of the live region', () => {
		const target = answered(efficiency01, { kind: 'best_discard', tile: '6m' });
		const live = byTestId(target, 'answer-feedback');
		expect(live.getAttribute('role')).toBe('status');
		expect(live.querySelector('table')).toBeNull();
		expect(byTestId(target, 'discard-table').querySelectorAll('th[scope="col"]')).toHaveLength(4);
	});
});

describe('AnswerPanel best_discard feedback', () => {
	it('a wrong pick: the options table with answers and pick marked, and why it is worse', () => {
		const target = answered(efficiency01, { kind: 'best_discard', tile: '6m' });
		const table = rows(target, 'discard-table');
		expect(table.filter((r) => r.answer).map((r) => r.tile)).toEqual(['4m', '7m']);
		expect(table.find((r) => r.picked)).toMatchObject({ tile: '6m', cells: ['1 away', '6', '12'] });
		expect(table[0].cells).toEqual(['Ready', '2', '4']);
		expect(lines(target)['discard-compare']).toEqual([
			'Discarding 6 Characters leaves you further from ready than discarding 4 Characters.'
		]);
	});

	it('a wrong pick at the same distance compares tiles accepted', () => {
		const target = answered(keepTwoSided, { kind: 'best_discard', tile: '2m' });
		expect(lines(target)['discard-compare']).toEqual([
			'After discarding 2 Characters, 7 unseen tiles improve your hand. After 5 Characters, 10 do.'
		]);
	});

	it('a right pick: the table, no comparison', () => {
		const target = answered(efficiency01, { kind: 'best_discard', tile: '7m' });
		expect(byTestId(target, 'answer-feedback').dataset.result).toBe('correct');
		expect(lines(target)).toEqual({});
		expect(rows(target, 'discard-table').find((r) => r.picked)).toMatchObject({
			tile: '7m',
			answer: true
		});
	});
});

describe('AnswerPanel winning_tiles feedback', () => {
	it('correct: names the waits that complete the hand but are too cheap or dead', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['1p', '7p'] });
		expect(lines(target)).toEqual({
			'below-minimum': [
				'2 Dots completes the hand, but scores only 1 faan on a discard and 2 self-drawn, below the minimum.',
				'5 Dots completes the hand, but scores only 1 faan on a discard and 2 self-drawn, below the minimum.'
			],
			dead: ['4 Dots would win, but every copy is already visible.']
		});
	});

	it('partial: says how many waits are still missing', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['7p'] });
		expect(byTestId(target, 'answer-feedback').dataset.result).toBe('partial');
		expect(lines(target)).toEqual({ missing: ['1 more winning tile to find.'] });
	});

	it('wrong: right picks, then each wrong pick with its reason, then the count missing', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['1p', '2p', '4p', '9m'] });
		expect(lines(target)).toEqual({
			right: ['Right: 1 Dot.'],
			'no-win': ["9 Characters doesn't complete your hand."],
			'below-minimum': [
				'2 Dots completes the hand, but scores only 1 faan on a discard and 2 self-drawn, below the minimum.'
			],
			dead: ['4 Dots would win, but every copy is already visible.'],
			missing: ['1 more winning tile to find.']
		});
	});
});

describe('AnswerPanel safe_discard feedback', () => {
	it('correct: the stated reason, and every tile with its outcome', () => {
		const target = answered(defence01, { kind: 'safe_discard', tile: '2m' });
		expect(lines(target)).toEqual({ why: ["Why it's safe: every copy is visible."] });
		const table = rows(target, 'safe-table');
		expect(table.filter((r) => r.answer).map((r) => r.tile)).toEqual(['1m', '2m', '6m']);
		expect(table.find((r) => r.tile === '4m')?.cells).toEqual([
			"Safe this time, but you couldn't know"
		]);
		expect(table.find((r) => r.tile === 'z5')?.cells).toEqual(['Deals in to North']);
	});

	it("safe by luck: not solved, and says you couldn't have known", () => {
		const target = answered(defence01, { kind: 'safe_discard', tile: '4m' });
		const live = byTestId(target, 'answer-feedback');
		expect(live.dataset.result).toBe('wrong');
		expect(live.dataset.lucky).toBe('true');
		expect(live.querySelector('.result')?.textContent).toBe(
			"4 Characters was safe this time, but you couldn't have known that."
		);
		expect(byTestId(target, 'answer-explain')).toBeNull();
	});

	it('deals in: names who it deals in to', () => {
		const target = answered(defence01, { kind: 'safe_discard', tile: 'z5' });
		expect(byTestId(target, 'answer-feedback').dataset.lucky).toBeUndefined();
		expect(lines(target)).toEqual({ 'deals-in': ['Red Dragon deals in to North.'] });
	});
});

describe('AnswerPanel count_faan feedback', () => {
	it('correct: the breakdown with guide links, the total and the points', () => {
		const onPatternSelect = vi.fn();
		const target = answered(faan02, { kind: 'count_faan', faan: 4 }, { onPatternSelect });
		expect(lines(target)).toEqual({ points: ['Worth 16 points.'] });
		const breakdown = byTestId(target, 'faan-breakdown');
		expect(breakdown.querySelectorAll('.pattern-row')).toHaveLength(2);
		expect(breakdown.querySelector('.total')?.textContent).toContain('4 faan');
		expect(breakdown.querySelector('.payments')).toBeNull();
		byTestId<HTMLButtonElement>(breakdown, 'faan-pattern-link').click();
		expect(onPatternSelect).toHaveBeenCalledWith('混一色');
	});

	it('wrong: says high or low, and keeps the breakdown hidden', () => {
		const high = answered(faan02, { kind: 'count_faan', faan: 6 });
		expect(lines(high)).toEqual({ 'faan-high': ['6 is too high.'] });
		expect(byTestId(high, 'faan-breakdown')).toBeNull();
		const low = answered(faan02, { kind: 'count_faan', faan: 2 });
		expect(lines(low)).toEqual({ 'faan-low': ['2 is too low.'] });
	});

	it('shows the claimed tile of a discard win', () => {
		const { target } = render(AnswerPanel, props(faan02, { claimedTile: '7s' }));
		const claimed = byTestId(target, 'claimed-tile');
		expect(claimed.querySelector('[data-tile="7s"]')).not.toBeNull();
		expect(claimed.textContent).toContain('7 Bamboo');
	});
});
