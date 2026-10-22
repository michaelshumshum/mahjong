import { describe, it, expect } from 'vitest';
import { hasTileArt } from '$lib/table/tile-code';
import { DEFAULT_RULESET } from '$lib/net/ruleset';
import { FAAN_PATTERNS } from '$lib/net/protocol.constants';
import { FAAN_PATTERN_LABEL } from './faan-pattern-labels';
import {
	GUIDE_ENTRIES,
	OVERRIDABLE_PATTERNS,
	guideTabs,
	matchesQuery,
	paidFaan,
	parseGroup,
	presetRules,
	scoredEntries
} from './faan-guide';

const names = (preset: string | null) => scoredEntries(presetRules(preset)).map((e) => e.pattern);
const entry = (pattern: string, rules: typeof DEFAULT_RULESET | null = DEFAULT_RULESET) =>
	scoredEntries(rules).find((e) => e.pattern === pattern);

describe('faan guide', () => {
	it('lists every scoring pattern exactly once', () => {
		const listed = GUIDE_ENTRIES.map((e) => e.pattern);
		expect(new Set(listed).size).toBe(listed.length);
		expect([...listed].sort()).toEqual(Object.keys(FAAN_PATTERN_LABEL).sort());
	});

	it('takes each faan value from the server pattern table', () => {
		for (const p of FAAN_PATTERNS) {
			const scored = entry(p.name, null);
			expect(scored?.faan, p.name).toBe(p.faan);
			expect(scored?.tab, p.name).toBe(p.limit ? 'limit' : p.faan);
		}
	});

	it('orders tabs by faan with limit hands last', () => {
		const tabs = guideTabs(scoredEntries(null));
		expect(tabs.at(-1)).toBe('limit');
		const numeric = tabs.filter((t) => t !== 'limit');
		expect(numeric).toEqual([...numeric].sort((a, b) => a - b));
	});

	it('every example group is made only of tiles with art', () => {
		for (const e of GUIDE_ENTRIES)
			for (const group of e.example) {
				const tiles = parseGroup(group);
				expect(tiles.join('')).toBe(group.replace(/^\*/, ''));
				expect(tiles.every(hasTileArt)).toBe(true);
			}
	});

	it('hand examples are complete 14-tile hands, kongs aside', () => {
		for (const e of GUIDE_ENTRIES) {
			const tiles = e.example.flatMap(parseGroup);
			if (tiles.length < 5 || e.pattern === '十八羅漢') continue;
			expect(tiles, e.pattern).toHaveLength(14);
		}
	});

	it('links only to patterns the guide lists', () => {
		const listed = new Set(GUIDE_ENTRIES.map((e) => e.pattern));
		for (const e of GUIDE_ENTRIES) for (const r of e.related ?? []) expect(listed).toContain(r);
	});

	it('filters patterns by preset hand sets', () => {
		expect(names(null)).toHaveLength(Object.keys(FAAN_PATTERN_LABEL).length);
		expect(names('hk_classic')).not.toContain('七對子');
		expect(names('hk_casual')).toContain('七對子');
		expect(names('hk_strict')).not.toContain('七對子');
		expect(names('hk_strict')).toContain('花么九');
	});

	it('lists chicken hand under 0 faan, and only where min faan is 0', () => {
		expect(entry('雞糊', { ...DEFAULT_RULESET, min_faan: 0 })?.tab).toBe(0);
		for (const id of ['hk_classic', 'hk_casual', 'hk_strict'])
			expect(names(id)).not.toContain('雞糊');
		expect(names(null)).toContain('雞糊');
	});

	it('applies overrides and drops patterns overridden to 0', () => {
		const rules = { ...DEFAULT_RULESET, faan_overrides: { 清一色: 5, 平糊: 0 } };
		expect(entry('清一色', rules)).toMatchObject({ faan: 5, defaultFaan: 7, tab: 5 });
		expect(entry('平糊', rules)).toBeUndefined();
	});

	it('pays a limit hand at most the cap', () => {
		const capped = { ...DEFAULT_RULESET, faan_cap: 8 };
		expect(paidFaan(entry('十三么', capped)!, capped)).toBe(8);
		expect(paidFaan(entry('十三么', null)!, null)).toBe(13);
	});

	it('searches English and Chinese names and descriptions', () => {
		const flush = GUIDE_ENTRIES.find((e) => e.pattern === '清一色')!;
		expect(matchesQuery(flush, 'full flush')).toBe(true);
		expect(matchesQuery(flush, '清一')).toBe(true);
		expect(matchesQuery(flush, 'no honors')).toBe(true);
		expect(matchesQuery(flush, 'dragon')).toBe(false);
	});

	it('offers overrides at each pattern’s real default', () => {
		expect(OVERRIDABLE_PATTERNS.find((p) => p.pattern === '清一色')).toMatchObject({
			faan: 7,
			tier: 7
		});
		expect(OVERRIDABLE_PATTERNS.find((p) => p.pattern === '字一色')?.tier).toBe('limit');
	});
});
