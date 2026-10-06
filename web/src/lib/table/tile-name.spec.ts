import { describe, it, expect } from 'vitest';
import en from '../../../messages/en.json';
import zhHant from '../../../messages/zh-Hant.json';
import { TILE_ASSET } from './tile-code';
import { TILE_NAME, tileName } from './tile-name';

describe('tileName', () => {
	it('names every tile with face art, and nothing else', () => {
		expect(Object.keys(TILE_NAME).sort()).toEqual(Object.keys(TILE_ASSET).sort());
	});

	it.each([
		['5s', '5 Bamboo'],
		['1m', '1 Character'],
		['9p', '9 Dots'],
		['z1', 'East Wind'],
		['z5', 'Red Dragon'],
		['f8', 'Winter Season']
	] as const)('names %s as %s', (code, name) => {
		expect(tileName(code)).toBe(name);
	});

	it('gives every tile a distinct name', () => {
		const names = Object.keys(TILE_NAME).map((code) => tileName(code as keyof typeof TILE_NAME));
		expect(new Set(names).size).toBe(names.length);
	});

	it.each([
		['en', en],
		['zh-Hant', zhHant]
	] as const)('has a %s message for every tile', (_locale, messages) => {
		for (const code of Object.keys(TILE_ASSET)) {
			expect(messages).toHaveProperty(`tileName_${code}`);
		}
	});

	it('uses the Chinese tile names in zh-Hant', () => {
		expect(zhHant.tileName_3s).toBe('三索');
		expect(zhHant.tileName_z5).toBe('紅中');
	});
});
