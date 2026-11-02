import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import TutorialCoach from './TutorialCoach.svelte';

describe('TutorialCoach', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount> | null = null;

	afterEach(() => {
		if (component) unmount(component);
		component = null;
		target?.remove();
	});

	function setup(props: Partial<Parameters<typeof TutorialCoach>[1]> = {}) {
		target = document.createElement('div');
		document.body.appendChild(target);
		const onNext = vi.fn();
		const onBack = vi.fn();
		component = mount(TutorialCoach, {
			target,
			props: {
				step: 3,
				total: 18,
				tip: 'Discard the Green Dragon.',
				move: false,
				wrongMoves: 0,
				busy: false,
				canBack: true,
				canNext: true,
				onBack,
				onNext,
				...props
			}
		});
		flushSync();
		const byTestId = (id: string) => target.querySelector<HTMLElement>(`[data-testid="${id}"]`);
		return { onNext, onBack, byTestId };
	}

	it('shows the counter and tip in a polite live region, with Back and Next', () => {
		const { onNext, onBack, byTestId } = setup();
		expect(target.textContent).toContain('Step 3 of 18');
		expect(byTestId('tutorial-tip')!.closest('[aria-live="polite"]')).not.toBeNull();
		byTestId('tutorial-next')!.click();
		byTestId('tutorial-back')!.click();
		expect(onNext).toHaveBeenCalledOnce();
		expect(onBack).toHaveBeenCalledOnce();
	});

	it('shows the step as a labelled progress bar', () => {
		const { byTestId } = setup({ step: 7 });
		const bar = byTestId('tutorial-progress')!;
		expect(bar.getAttribute('role')).toBe('progressbar');
		expect(bar.getAttribute('aria-label')).toBe('Tutorial progress');
		expect(bar.getAttribute('aria-valuemin')).toBe('0');
		expect(bar.getAttribute('aria-valuemax')).toBe('18');
		expect(bar.getAttribute('aria-valuenow')).toBe('7');
		expect(bar.getAttribute('aria-valuetext')).toBe('Step 7 of 18');
		const fill = bar.firstElementChild as HTMLElement;
		expect(Number(fill.style.getPropertyValue('--progress'))).toBeCloseTo(7 / 18);
	});

	it('has no Next at a move, and says so after a wrong one', () => {
		const { byTestId } = setup({ move: true, canNext: false, wrongMoves: 1 });
		expect(byTestId('tutorial-next')).toBeNull();
		expect(byTestId('tutorial-hint')!.textContent).toContain('Not that one');
	});

	it('says the others are playing while busy, with no hint', () => {
		const { byTestId } = setup({ busy: true, move: true, wrongMoves: 2, canNext: false });
		expect(byTestId('tutorial-watching')).not.toBeNull();
		expect(byTestId('tutorial-hint')).toBeNull();
	});

	it('moves focus to Next when nothing has it', async () => {
		const { byTestId } = setup();
		await new Promise((resolve) => setTimeout(resolve, 10));
		expect(document.activeElement).toBe(byTestId('tutorial-next'));
	});
});
