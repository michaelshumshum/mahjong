import { describe, it, expect, afterEach, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import CoachMarks from './CoachMarks.svelte';

describe('CoachMarks', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount> | null = null;

	afterEach(() => {
		if (component) unmount(component);
		component = null;
		target?.remove();
	});

	function setup(discardMode: 'two-step' | 'one-tap' = 'two-step') {
		target = document.createElement('div');
		document.body.appendChild(target);
		const onStepChange = vi.fn();
		const onDone = vi.fn();
		component = mount(CoachMarks, { target, props: { discardMode, onStepChange, onDone } });
		flushSync();
		const next = () => {
			(target.querySelector('[data-testid="coach-next"]') as HTMLButtonElement).click();
			flushSync();
		};
		return { onStepChange, onDone, next };
	}

	it('walks hand -> discards -> claims, then finishes', () => {
		const { onStepChange, onDone, next } = setup();
		expect(target.textContent).toContain('lift it');
		expect(onStepChange).toHaveBeenLastCalledWith('hand');
		next();
		expect(target.textContent).toContain('newest discard');
		expect(onStepChange).toHaveBeenLastCalledWith('discards');
		next();
		expect(target.textContent).toContain('claim a discard');
		expect(onStepChange).toHaveBeenLastCalledWith(null);
		expect(onDone).not.toHaveBeenCalled();
		next();
		expect(onDone).toHaveBeenCalledOnce();
	});

	it('matches the discard tip to one-tap mode', () => {
		setup('one-tap');
		expect(target.textContent).toContain('Tap a tile in your hand to discard it.');
	});

	it('skip finishes immediately', () => {
		const { onDone } = setup();
		(target.querySelector('[data-testid="coach-skip"]') as HTMLButtonElement).click();
		flushSync();
		expect(onDone).toHaveBeenCalledOnce();
	});
});
