import { describe, it, expect } from 'vitest';
import en from '../../../messages/en/account.json';
import zh from '../../../messages/zh-Hant/account.json';

// adr 0028 phase 7 replaced the phase 3 placeholder wording
describe('training consent wording', () => {
	it.each([
		['en', en],
		['zh-Hant', zh]
	])('is final in %s', (_, messages) => {
		const entries = Object.entries(messages).filter(([key]) =>
			key.startsWith('trainingConsentField_')
		);
		expect(entries.map(([key]) => key)).toEqual([
			'trainingConsentField_label',
			'trainingConsentField_description'
		]);
		for (const [, text] of entries) {
			expect(text).not.toMatch(/draft|草擬/i);
		}
	});
});
