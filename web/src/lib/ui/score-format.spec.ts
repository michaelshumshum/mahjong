import { describe, expect, it, vi } from 'vitest';

vi.mock('$lib/paraglide/runtime.js', () => ({ getLocale: vi.fn(() => 'en') }));

import { getLocale } from '$lib/paraglide/runtime.js';
import { formatSigned } from './score-format';

describe('formatSigned', () => {
	it('signs positives and negatives, never zero', () => {
		expect([40, 0, -30].map(formatSigned)).toEqual(['+40', '0', '-30']);
	});

	it('does not group thousands', () => {
		expect(formatSigned(1536)).toBe('+1536');
	});

	it('keeps the same signs in zh-Hant', () => {
		vi.mocked(getLocale).mockReturnValue('zh-Hant');
		expect([8, 0, -8].map(formatSigned)).toEqual(['+8', '0', '-8']);
	});
});
