import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import SealStamp from './SealStamp.svelte';

describe('SealStamp', () => {
	afterEach(cleanupAll);

	it('renders the glyph as a round badge placed on the claimer side', () => {
		const { target } = render(SealStamp, { glyph: '碰', position: 'self' });
		const stamp = target.querySelector<HTMLElement>('.seal-stamp');
		expect(stamp?.textContent?.trim()).toBe('碰');
		expect(stamp?.dataset.position).toBe('self');
		expect(stamp?.classList.contains('seal-stamp--placed')).toBe(true);
		expect(getComputedStyle(stamp!).borderRadius).toBe('50%');
	});

	it('stays unplaced without a position (demo preview)', () => {
		const { target } = render(SealStamp, { glyph: '上' });
		const stamp = target.querySelector('.seal-stamp');
		expect(stamp?.classList.contains('seal-stamp--placed')).toBe(false);
	});
});
