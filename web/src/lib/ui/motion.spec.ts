import { afterEach, describe, expect, it, vi } from 'vitest';
import { applyMotionPref, isMotionReduced } from './motion';

function fakeRoot(): HTMLElement {
	return { dataset: {} } as unknown as HTMLElement;
}

function stubOsReduced(reduced: boolean): void {
	vi.stubGlobal('window', { matchMedia: () => ({ matches: reduced }) });
}

describe('motion', () => {
	afterEach(() => vi.unstubAllGlobals());

	it('applyMotionPref writes the pref to data-motion', () => {
		const root = fakeRoot();
		applyMotionPref('reduced', root);
		expect(root.dataset.motion).toBe('reduced');
	});

	it('an explicit pref overrides the OS setting', () => {
		const root = fakeRoot();
		stubOsReduced(false);
		applyMotionPref('reduced', root);
		expect(isMotionReduced(root)).toBe(true);

		stubOsReduced(true);
		applyMotionPref('full', root);
		expect(isMotionReduced(root)).toBe(false);
	});

	it.each([true, false])('system (or unset) follows prefers-reduced-motion=%s', (reduced) => {
		stubOsReduced(reduced);
		const root = fakeRoot();
		expect(isMotionReduced(root)).toBe(reduced);
		applyMotionPref('system', root);
		expect(isMotionReduced(root)).toBe(reduced);
	});
});
