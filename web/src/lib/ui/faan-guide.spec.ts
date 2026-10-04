import { describe, it, expect } from 'vitest';
import { hasTileArt } from '$lib/table/tile-code';
import { FAAN_PATTERN_LABEL } from './faan-pattern-labels';
import { GUIDE, GUIDE_TABS, guideEntries, parseGroup } from './faan-guide';

describe('faan guide', () => {
	it('lists every scoring pattern exactly once', () => {
		const listed = GUIDE_TABS.flatMap((t) => guideEntries(t).map((e) => e.pattern));
		expect(new Set(listed).size).toBe(listed.length);
		expect([...listed].sort()).toEqual(Object.keys(FAAN_PATTERN_LABEL).sort());
	});

	it('has an entry list for every tab', () => {
		for (const tab of GUIDE_TABS) expect(GUIDE[String(tab)].length).toBeGreaterThan(0);
	});

	it('every example group is made only of tiles with art', () => {
		for (const tab of GUIDE_TABS)
			for (const entry of guideEntries(tab))
				for (const group of entry.example) {
					const tiles = parseGroup(group);
					expect(tiles.join('')).toBe(group);
					expect(tiles.every(hasTileArt)).toBe(true);
				}
	});

	it('full-hand examples have 14 tiles unless they use kongs-free partial shapes', () => {
		const fullHands = ['平糊', '缺一門', '對對糊', '混一色', '清一色', '大四喜', '字一色'];
		for (const tab of GUIDE_TABS)
			for (const entry of guideEntries(tab))
				if (fullHands.includes(entry.pattern))
					expect(entry.example.flatMap(parseGroup)).toHaveLength(14);
	});
});
