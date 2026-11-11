import { afterEach, describe, expect, it } from 'vitest';
import { flushSync } from 'svelte';
import { cleanupAll, render } from '$lib/table/test-render';
import Avatar from './Avatar.svelte';

describe('Avatar', () => {
	afterEach(cleanupAll);

	it('shows the initial without a picture', () => {
		const { target } = render(Avatar, { name: ' ann' });
		flushSync();
		expect(target.querySelector('.avatar')?.textContent?.trim()).toBe('A');
		expect(target.querySelector('img')).toBeNull();
	});

	it('shows the picture without sending a referrer', () => {
		const { target } = render(Avatar, { name: 'ann', src: 'https://example.test/a.png' });
		flushSync();
		const img = target.querySelector('img')!;
		expect(img.getAttribute('src')).toBe('https://example.test/a.png');
		expect(img.getAttribute('referrerpolicy')).toBe('no-referrer');
		expect(img.alt).toBe('');
	});

	it('falls back to the initial when the picture fails to load', () => {
		const { target } = render(Avatar, { name: 'ann', src: 'https://example.test/a.png' });
		flushSync();
		target.querySelector('img')!.dispatchEvent(new Event('error'));
		flushSync();
		expect(target.querySelector('img')).toBeNull();
		expect(target.querySelector('.avatar')?.textContent?.trim()).toBe('A');
	});
});
