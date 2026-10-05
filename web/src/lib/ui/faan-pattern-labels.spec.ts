import { describe, it, expect, vi } from 'vitest';
import { createMessagesProxy } from '../../test/mocks';

vi.mock('$lib/paraglide/messages.js', () => ({ m: createMessagesProxy() }));

import { FAAN_PATTERN_LABEL, faanPatternLabel } from './faan-pattern-labels';

describe('faanPatternLabel', () => {
	it('resolves a real wire pattern name (the Chinese key hand_end.faan_breakdown sends) to its message', () => {
		expect(faanPatternLabel('混一色')).toBe('faanPattern_halfFlush');
	});

	it('falls through unchanged for a name with no entry, e.g. a mock-fixture literal', () => {
		expect(faanPatternLabel('All Sequences')).toBe('All Sequences');
		expect(faanPatternLabel('Chicken Hand')).toBe('Chicken Hand');
	});

	it('covers all 30 patterns in mahjong_core.scoring.patterns.PATTERNS plus 雞糊 (scoring/faan.py)', () => {
		expect(Object.keys(FAAN_PATTERN_LABEL)).toHaveLength(31);
	});
});
