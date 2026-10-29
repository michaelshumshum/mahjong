import { flushSync } from 'svelte';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanupAll, render } from '$lib/table/test-render';
import isolatedHonour from './generated/basics-isolated-honour.json';
import simpleHand from './generated/basics-simple-hand.json';
import twoSidedWait from './generated/basics-two-sided-wait.json';
import type { Lesson } from './generated/lessons';
import AnswerPanel from './AnswerPanel.svelte';

afterEach(cleanupAll);

function props(lesson: unknown, extra: Record<string, unknown> = {}) {
	return {
		lesson: lesson as Lesson,
		discardMode: 'two-step' as const,
		result: null,
		attempts: 0,
		explanation: 'because',
		onAnswer: vi.fn(),
		...extra
	};
}

function byTestId<T extends HTMLElement>(target: HTMLElement, id: string): T {
	return target.querySelector<T>(`[data-testid="${id}"]`)!;
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
		const wrong = render(AnswerPanel, props(simpleHand, { result: 'wrong', attempts: 1 }));
		expect(byTestId(wrong.target, 'answer-feedback').dataset.result).toBe('wrong');
		expect(byTestId(wrong.target, 'answer-explain')).toBeNull();
		const right = render(AnswerPanel, props(simpleHand, { result: 'correct', attempts: 2 }));
		expect(byTestId(right.target, 'answer-explain').textContent).toBe('because');
	});
});
