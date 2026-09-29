import { describe, expect, it } from 'vitest';
import { TABLE_CODE_LENGTH } from './table-code';

describe('TABLE_CODE_LENGTH', () => {
	it('is 6', () => {
		expect(TABLE_CODE_LENGTH).toBe(6);
	});

	it('matches the length of a sample table code', () => {
		const sample = 'ABC123';
		expect(sample).toHaveLength(TABLE_CODE_LENGTH);
	});
});
