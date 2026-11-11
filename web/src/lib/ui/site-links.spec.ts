import { describe, it, expect } from 'vitest';
import { ISSUES_URL, SOURCE_REPO_URL, contactEmail, effectiveDateLabel } from './site-links';

describe('contactEmail', () => {
	it('is null when unset or blank, so the pages fall back to the issues link', () => {
		expect(contactEmail(undefined)).toBeNull();
		expect(contactEmail('  ')).toBeNull();
	});

	it('trims a configured address', () => {
		expect(contactEmail(' hello@example.com ')).toBe('hello@example.com');
	});
});

describe('effectiveDateLabel', () => {
	it('formats the date in each locale, in UTC', () => {
		expect(effectiveDateLabel('en')).toBe('November 11, 2026');
		expect(effectiveDateLabel('zh-Hant')).toBe('2026年11月11日');
	});
});

it('points the issues link at the source repo', () => {
	expect(ISSUES_URL).toBe(`${SOURCE_REPO_URL}/issues`);
});
