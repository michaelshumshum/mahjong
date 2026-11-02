import { flushSync } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanupAll, render } from '$lib/table/test-render';
import defence02 from './generated/defence-02.json';
import efficiency02 from './generated/efficiency-02.json';
import faan03 from './generated/faan-03.json';
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
	it('discard kinds: the hand is the input, and Check grades the picked tile', () => {
		const none = render(AnswerPanel, props(isolatedHonour)).target;
		expect(none.querySelector('.hint')).not.toBeNull();
		expect(byTestId<HTMLButtonElement>(none, 'answer-check').disabled).toBe(true);

		const onCheckSelected = vi.fn();
		const picked = render(
			AnswerPanel,
			props(isolatedHonour, { selectedTile: 'z5', onCheckSelected })
		).target;
		const check = byTestId<HTMLButtonElement>(picked, 'answer-check');
		expect(check.disabled).toBe(false);
		check.click();
		expect(onCheckSelected).toHaveBeenCalledOnce();
	});

	it('offers Show answer after a miss only, until it is used', () => {
		const onReveal = vi.fn();
		const wrong = answered(simpleHand, { kind: 'count_faan', faan: 2 }, { onReveal });
		byTestId<HTMLButtonElement>(wrong, 'answer-reveal').click();
		expect(onReveal).toHaveBeenCalledOnce();
		const partial = answered(waits12, { kind: 'winning_tiles', tiles: ['7p'] }, { onReveal });
		expect(byTestId(partial, 'answer-reveal')).not.toBeNull();
		const right = answered(simpleHand, { kind: 'count_faan', faan: 3 }, { onReveal });
		expect(byTestId(right, 'answer-reveal')).toBeNull();
		const shown = answered(
			simpleHand,
			{ kind: 'count_faan', faan: 2 },
			{ onReveal, revealed: true }
		);
		expect(byTestId(shown, 'answer-reveal')).toBeNull();
		expect(byTestId(shown, 'answer-feedback').dataset.revealed).toBe('true');
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

	it('shows the explanation once the answer is correct or revealed', () => {
		const wrong = answered(simpleHand, { kind: 'count_faan', faan: 2 });
		expect(byTestId(wrong, 'answer-feedback').dataset.result).toBe('wrong');
		expect(byTestId(wrong, 'answer-explain')).toBeNull();
		const right = answered(simpleHand, { kind: 'count_faan', faan: 3 });
		expect(byTestId(right, 'answer-explain').textContent).toBe('because');
		const shown = answered(simpleHand, { kind: 'count_faan', faan: 2 }, { revealed: true });
		expect(byTestId(shown, 'answer-feedback').dataset.result).toBe('wrong');
		expect(byTestId(shown, 'answer-explain').textContent).toBe('because');
	});

	it('keeps the tables out of the live region', () => {
		const target = answered(efficiency02, { kind: 'best_discard', tile: '4s' });
		const live = byTestId(target, 'answer-feedback');
		expect(live.getAttribute('role')).toBe('status');
		expect(live.querySelector('table')).toBeNull();
		expect(byTestId(target, 'discard-table').querySelectorAll('th[scope="col"]')).toHaveLength(4);
	});
});

describe('AnswerPanel best_discard feedback', () => {
	it('a wrong pick: why it is worse, and no table to give the answer away', () => {
		const target = answered(efficiency02, { kind: 'best_discard', tile: '3m' });
		expect(lines(target)['discard-compare']).toHaveLength(1);
		expect(byTestId(target, 'discard-table')).toBeNull();
		expect(byTestId(target, 'answer-explain')).toBeNull();
	});

	it('a wrong pick revealed: the options table with answers and pick marked', () => {
		const target = answered(efficiency02, { kind: 'best_discard', tile: '3m' }, { revealed: true });
		const table = rows(target, 'discard-table');
		expect(table.filter((r) => r.answer).map((r) => r.tile)).toEqual(['9p', '4s']);
		expect(table.find((r) => r.picked)).toMatchObject({
			tile: '3m',
			cells: ['2 away', '16', '41']
		});
		expect(table[0].cells).toEqual(['1 away', '3', '10']);
		expect(lines(target)['discard-compare']).toEqual([
			'Discarding 3 Characters leaves you further from ready than discarding 9 Dots.'
		]);
	});

	it('a wrong pick at the same distance compares tiles accepted', () => {
		const target = answered(keepTwoSided, { kind: 'best_discard', tile: '2m' });
		expect(lines(target)['discard-compare']).toEqual([
			'Unseen tiles that help: 7 after discarding 2 Characters, 10 after discarding 5 Characters.'
		]);
	});

	it('a right pick: the table, no comparison', () => {
		const target = answered(efficiency02, { kind: 'best_discard', tile: '4s' });
		expect(byTestId(target, 'answer-feedback').dataset.result).toBe('correct');
		expect(lines(target)).toEqual({});
		expect(rows(target, 'discard-table').find((r) => r.picked)).toMatchObject({
			tile: '4s',
			answer: true
		});
	});
});

describe('AnswerPanel winning_tiles feedback', () => {
	it('correct: names the waits that complete the hand but are too cheap or dead', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['1p', '7p'] });
		expect(lines(target)).toEqual({
			'below-minimum': [
				"2 Dots completes the hand, but it's worth only 1 faan on a discard win and 2 self-drawn: below the minimum either way.",
				"5 Dots completes the hand, but it's worth only 1 faan on a discard win and 2 self-drawn: below the minimum either way."
			],
			dead: ['4 Dots would win, but every copy is already visible.']
		});
	});

	it('partial: says how many waits are still missing', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['7p'] });
		expect(byTestId(target, 'answer-feedback').dataset.result).toBe('partial');
		expect(lines(target)).toEqual({ missing: ['1 more winning tile to find.'] });
	});

	it('wrong: each wrong pick with its reason and the count missing, never a right tile', () => {
		const target = answered(waits12, { kind: 'winning_tiles', tiles: ['1p', '2p', '4p', '9m'] });
		expect(lines(target)).toEqual({
			'no-win': ["9 Characters doesn't complete your hand."],
			'below-minimum': [
				"2 Dots completes the hand, but it's worth only 1 faan on a discard win and 2 self-drawn: below the minimum either way."
			],
			dead: ['4 Dots would win, but every copy is already visible.'],
			missing: ['1 more winning tile to find.']
		});
	});

	it('revealed: every winning tile, the wrong picks, then the teaching points left', () => {
		const target = answered(
			waits12,
			{ kind: 'winning_tiles', tiles: ['1p', '2p', '4p', '9m'] },
			{ revealed: true }
		);
		expect(lines(target)).toEqual({
			answer: ['The winning tiles: 1 Dot and 7 Dots.'],
			'no-win': ["9 Characters doesn't complete your hand."],
			'below-minimum': [
				"2 Dots completes the hand, but it's worth only 1 faan on a discard win and 2 self-drawn: below the minimum either way.",
				"5 Dots completes the hand, but it's worth only 1 faan on a discard win and 2 self-drawn: below the minimum either way."
			],
			dead: ['4 Dots would win, but every copy is already visible.']
		});
		expect(byTestId(target, 'answer-explain').textContent).toBe('because');
	});
});

describe('AnswerPanel safe_discard feedback', () => {
	it('correct: the stated reason, and every tile with its outcome', () => {
		const target = answered(defence02, { kind: 'safe_discard', tile: '8s' });
		expect(lines(target)).toEqual({
			why: ["Why it's safe: every copy is visible and no chow can be waiting on it."]
		});
		const table = rows(target, 'safe-table');
		expect(table.filter((r) => r.answer).map((r) => r.tile)).toEqual(['8s']);
		expect(table.find((r) => r.tile === '2m')?.cells).toEqual([
			"Safe this time, but you couldn't have known"
		]);
		expect(table.find((r) => r.tile === 'z5')?.cells).toEqual(['Deals in to East']);
	});

	it("safe by luck: not solved, and says you couldn't have known", () => {
		const target = answered(defence02, { kind: 'safe_discard', tile: '2m' });
		const live = byTestId(target, 'answer-feedback');
		expect(live.dataset.result).toBe('wrong');
		expect(live.dataset.lucky).toBe('true');
		expect(live.querySelector('.result')?.textContent).toBe(
			"2 Characters was safe this time, but you couldn't have known that."
		);
		expect(byTestId(target, 'answer-explain')).toBeNull();
		expect(byTestId(target, 'safe-table')).toBeNull();
	});

	it('deals in: names who it deals in to, and the table waits for a reveal', () => {
		const target = answered(defence02, { kind: 'safe_discard', tile: 'z5' });
		expect(byTestId(target, 'answer-feedback').dataset.lucky).toBeUndefined();
		expect(lines(target)).toEqual({ 'deals-in': ['Red Dragon deals in to East.'] });
		expect(byTestId(target, 'safe-table')).toBeNull();
		const shown = answered(defence02, { kind: 'safe_discard', tile: 'z5' }, { revealed: true });
		const table = rows(shown, 'safe-table');
		expect(table.filter((r) => r.answer).map((r) => r.tile)).toEqual(['8s']);
		expect(table.find((r) => r.picked)?.tile).toBe('z5');
	});
});

describe('AnswerPanel count_faan feedback', () => {
	it('correct: the breakdown with guide links, the total and the points', () => {
		const onPatternSelect = vi.fn();
		const target = answered(faan03, { kind: 'count_faan', faan: 6 }, { onPatternSelect });
		expect(lines(target)).toEqual({ points: ['Worth 32 points.'] });
		const breakdown = byTestId(target, 'faan-breakdown');
		expect(breakdown.querySelectorAll('.pattern-row')).toHaveLength(2);
		expect(breakdown.querySelector('.total')?.textContent).toContain('6 faan');
		expect(breakdown.querySelector('.payments')).toBeNull();
		byTestId<HTMLButtonElement>(breakdown, 'faan-pattern-link').click();
		expect(onPatternSelect).toHaveBeenCalledWith('對對糊');
	});

	it('wrong: says high or low, and keeps the breakdown hidden', () => {
		const high = answered(faan03, { kind: 'count_faan', faan: 8 });
		expect(lines(high)).toEqual({ 'faan-high': ['8 faan is too high.'] });
		expect(byTestId(high, 'faan-breakdown')).toBeNull();
		const low = answered(faan03, { kind: 'count_faan', faan: 4 });
		expect(lines(low)).toEqual({ 'faan-low': ['4 faan is too low.'] });
	});

	it('revealed: the miss, the points and the breakdown', () => {
		const target = answered(faan03, { kind: 'count_faan', faan: 8 }, { revealed: true });
		expect(lines(target)).toEqual({
			'faan-high': ['8 faan is too high.'],
			points: ['Worth 32 points.']
		});
		expect(byTestId(target, 'faan-breakdown').querySelector('.total')?.textContent).toContain(
			'6 faan'
		);
	});

	it('shows the claimed tile of a discard win', () => {
		const { target } = render(AnswerPanel, props(faan03, { claimedTile: '7s' }));
		const claimed = byTestId(target, 'claimed-tile');
		expect(claimed.querySelector('[data-tile="7s"]')).not.toBeNull();
		expect(claimed.textContent).toContain('7 Bamboo');
	});
});
