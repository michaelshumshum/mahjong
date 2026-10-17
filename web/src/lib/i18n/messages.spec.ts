import { describe, it, expect } from 'vitest';
import settings from '../../../project.inlang/settings.json';

const files = import.meta.glob<Record<string, unknown>>('../../../messages/*/*.json', {
	eager: true,
	import: 'default'
});

const catalog: Record<string, Record<string, string[]>> = {};
for (const [path, messages] of Object.entries(files)) {
	const [locale, file] = path.split('/').slice(-2);
	catalog[locale] ??= {};
	catalog[locale][file] = Object.keys(messages).filter((key) => key !== '$schema');
}

const patterns = settings['plugin.inlang.messageFormat'].pathPattern;
const registered = patterns.map((pattern) => pattern.split('/').at(-1)!);
const prefix = (key: string) => key.split('_')[0];

describe('message catalog', () => {
	it('has a directory for every locale and nothing else', () => {
		expect(Object.keys(catalog).sort()).toEqual([...settings.locales].sort());
	});

	it.each(settings.locales)('registers exactly the %s files in pathPattern', (locale) => {
		expect(Object.keys(catalog[locale]).sort()).toEqual([...registered].sort());
	});

	it.each(settings.locales)('has the base locale keys, in order, in every %s file', (locale) => {
		for (const file of registered) {
			expect(catalog[locale][file], file).toEqual(catalog[settings.baseLocale][file]);
		}
	});

	it('keeps each key prefix in a single file', () => {
		const home = new Map<string, string>();
		for (const file of registered) {
			for (const key of catalog[settings.baseLocale][file]) {
				expect(home.get(prefix(key)) ?? file, key).toBe(file);
				home.set(prefix(key), file);
			}
		}
	});
});
