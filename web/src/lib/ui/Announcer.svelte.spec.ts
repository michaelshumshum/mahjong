import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { cleanupAll, render } from '$lib/table/test-render';
import Announcer from './Announcer.svelte';

describe('Announcer', () => {
	afterEach(() => {
		cleanupAll();
		vi.useRealTimers();
	});

	function region(): HTMLElement {
		return document.querySelector('[data-testid="announcer"]')!;
	}

	it('is one polite, atomic live region', () => {
		render(Announcer, {});
		expect(region().getAttribute('aria-live')).toBe('polite');
		expect(region().getAttribute('aria-atomic')).toBe('true');
	});

	it('settles a burst into one update, keeping only the latest lines', () => {
		vi.useFakeTimers();
		const { instance } = render(Announcer, {});
		const announce = instance.announce as (lines: string | string[]) => void;
		announce(['a', 'b']);
		vi.advanceTimersByTime(200);
		announce(['c', 'd', 'e']);
		flushSync();
		expect(region().textContent?.trim()).toBe('');
		vi.advanceTimersByTime(300);
		flushSync();
		expect(region().textContent?.replace('​', '').trim()).toBe('b. c. d. e');
	});

	it('changes the region text even for an identical repeat', () => {
		vi.useFakeTimers();
		const { instance } = render(Announcer, {});
		const announce = instance.announce as (lines: string) => void;
		announce('Your turn');
		vi.advanceTimersByTime(300);
		flushSync();
		const first = region().textContent;
		announce('Your turn');
		vi.advanceTimersByTime(300);
		flushSync();
		expect(region().textContent).not.toBe(first);
	});
});
