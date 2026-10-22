import { m } from '$lib/paraglide/messages.js';
import { RULESET_PRESET_RULES, type HandSet, type RuleSet } from '$lib/net/ruleset';
import { CHICKEN_HAND, FAAN_PATTERNS } from '$lib/net/protocol.constants';
import type { TileCode } from '$lib/table/tile-code';
import { faanPatternLabel } from './faan-pattern-labels';

export type GuideTag = 'situational' | 'concealed' | 'flowers';

export interface GuideEntry {
	pattern: string;
	description: () => string;
	// each string is one group (meld, pair, ...) of concatenated tile codes; a leading '*' marks
	// a group the pattern is about. empty = no tile example
	example: string[];
	tags?: GuideTag[];
	// look-alikes worth telling apart
	related?: string[];
}

export type GuideTab = number | 'limit';

export interface ScoredEntry extends GuideEntry {
	handSet: HandSet;
	// under the rules in view: an override, else the server default
	faan: number;
	defaultFaan: number;
	limit: boolean;
	tab: GuideTab;
}

const TILE_RE = /[1-9][mps]|[zf][1-9]/g;
const KEY_GROUP = '*';

export function parseGroup(group: string): TileCode[] {
	return (group.match(TILE_RE) ?? []) as TileCode[];
}

export function isKeyGroup(group: string): boolean {
	return group.startsWith(KEY_GROUP);
}

// display order within a tab; faan values and hand sets come from the server (FAAN_PATTERNS).
export const GUIDE_ENTRIES: GuideEntry[] = [
	{ pattern: '雞糊', description: m.guide_descChickenHand, example: [] },
	{
		pattern: '平糊',
		description: m.guide_descAllSequences,
		example: ['1m2m3m', '4p5p6p', '7p8p9p', '2s3s4s', '8m8m']
	},
	{
		pattern: '門風',
		description: m.guide_descSeatWind,
		example: ['*z1z1z1', '2m3m4m', '5p6p7p', '7s8s9s', '5s5s'],
		related: ['圈風']
	},
	{
		pattern: '圈風',
		description: m.guide_descPrevailingWind,
		example: ['*z2z2z2', '1m2m3m', '4p5p6p', '6s7s8s', '9m9m'],
		related: ['門風']
	},
	{
		pattern: '箭刻',
		description: m.guide_descDragonPung,
		example: ['*z5z5z5', '3m4m5m', '2p3p4p', '6s7s8s', '1p1p'],
		related: ['小三元', '大三元']
	},
	{
		pattern: '正花',
		description: m.guide_descSeatFlower,
		example: ['f1'],
		tags: ['flowers'],
		related: ['一台花']
	},
	{
		pattern: '無花',
		description: m.guide_descNoFlowers,
		example: [],
		tags: ['flowers'],
		related: ['正花']
	},
	{
		pattern: '自摸',
		description: m.guide_descSelfDraw,
		example: [],
		tags: ['situational'],
		related: ['門前清']
	},
	{
		pattern: '門前清',
		description: m.guide_descFullyConcealed,
		example: [],
		tags: ['concealed'],
		related: ['自摸']
	},
	{
		pattern: '海底撈月',
		description: m.guide_descWinOnLastWallTile,
		example: [],
		tags: ['situational']
	},
	{
		pattern: '槓上開花',
		description: m.guide_descWinOnKongReplacement,
		example: [],
		tags: ['situational'],
		related: ['連槓開花']
	},
	{
		pattern: '搶槓',
		description: m.guide_descRobbingTheKong,
		example: [],
		tags: ['situational']
	},
	{
		pattern: '一台花',
		description: m.guide_descFlowerSet,
		example: ['f1f2f3f4'],
		tags: ['flowers'],
		related: ['正花']
	},
	{
		pattern: '對對糊',
		description: m.guide_descAllPungs,
		example: ['2m2m2m', '5p5p5p', '8s8s8s', 'z3z3z3', '6m6m'],
		related: ['四暗刻', '花么九']
	},
	{
		pattern: '混一色',
		description: m.guide_descHalfFlush,
		example: ['1p2p3p', '4p5p6p', '9p9p9p', '*z5z5z5', '*z1z1'],
		related: ['清一色', '字一色']
	},
	{
		pattern: '花么九',
		description: m.guide_descMixedTerminals,
		example: ['1m1m1m', '9p9p9p', '1s1s1s', 'z4z4z4', 'z7z7'],
		related: ['對對糊', '清么九']
	},
	{
		pattern: '七對子',
		description: m.guide_descSevenPairs,
		example: ['2m2m', '5m5m', '3p3p', '8p8p', '1s1s', '6s6s', 'z6z6'],
		tags: ['concealed']
	},
	{
		pattern: '小三元',
		description: m.guide_descSmallThreeDragons,
		example: ['*z5z5z5', '*z6z6z6', '*z7z7', '3s4s5s', '2m2m2m'],
		related: ['大三元', '箭刻']
	},
	{
		pattern: '小四喜',
		description: m.guide_descSmallFourWinds,
		example: ['*z1z1z1', '*z2z2z2', '*z3z3z3', '*z4z4', '4p5p6p'],
		related: ['大四喜']
	},
	{
		pattern: '清一色',
		description: m.guide_descFullFlush,
		example: ['1s2s3s', '4s5s6s', '7s8s9s', '3s3s3s', '5s5s'],
		related: ['混一色', '九蓮寶燈']
	},
	{
		pattern: '大三元',
		description: m.guide_descBigThreeDragons,
		example: ['*z5z5z5', '*z6z6z6', '*z7z7z7', '4m5m6m', '8s8s'],
		related: ['小三元']
	},
	{
		pattern: '四暗刻',
		description: m.guide_descFourConcealedPungs,
		example: ['2m2m2m', '5p5p5p', '8s8s8s', 'z5z5z5', '4m4m'],
		tags: ['concealed'],
		related: ['對對糊']
	},
	{
		pattern: '連槓開花',
		description: m.guide_descChainedKong,
		example: [],
		tags: ['situational'],
		related: ['槓上開花']
	},
	{
		pattern: '大四喜',
		description: m.guide_descBigFourWinds,
		example: ['*z1z1z1', '*z2z2z2', '*z3z3z3', '*z4z4z4', '5s5s'],
		related: ['小四喜']
	},
	{
		pattern: '十八羅漢',
		description: m.guide_descEighteenArhats,
		example: ['2m2m2m2m', '5p5p5p5p', '8s8s8s8s', 'z5z5z5z5', '4m4m'],
		related: ['對對糊']
	},
	{
		pattern: '十三么',
		description: m.guide_descThirteenOrphans,
		example: ['1m9m1p9p1s9sz1z2z3z4z5z6z7z7'],
		tags: ['concealed']
	},
	{
		pattern: '字一色',
		description: m.guide_descAllHonors,
		example: ['z1z1z1', 'z3z3z3', 'z5z5z5', 'z7z7z7', 'z2z2'],
		related: ['混一色']
	},
	{
		pattern: '清么九',
		description: m.guide_descAllTerminals,
		example: ['1m1m1m', '9m9m9m', '1p1p1p', '9s9s9s', '1s1s'],
		related: ['花么九']
	},
	{
		pattern: '九蓮寶燈',
		description: m.guide_descNineGates,
		example: ['1p1p1p2p3p4p5p6p7p8p9p9p9p', '*5p'],
		tags: ['concealed'],
		related: ['清一色']
	},
	{
		pattern: '天糊',
		description: m.guide_descHeavenlyHand,
		example: [],
		tags: ['situational'],
		related: ['地糊']
	},
	{
		pattern: '地糊',
		description: m.guide_descEarthlyHand,
		example: [],
		tags: ['situational'],
		related: ['天糊']
	}
];

interface PatternInfo {
	handSet: HandSet;
	faan: number;
	limit: boolean;
}

// 雞糊 isn't gated by a hand set (docs/rules.md §7), only by min_faan; CLASSIC is always-on enough
// for the hand-set filter to never hide it.
const PATTERN_INFO: Record<string, PatternInfo> = {
	...Object.fromEntries(FAAN_PATTERNS.map((p) => [p.name, p])),
	[CHICKEN_HAND.name]: { handSet: 'CLASSIC', faan: CHICKEN_HAND.faan, limit: false }
};

export function patternInfo(pattern: string): PatternInfo | undefined {
	return PATTERN_INFO[pattern];
}

export function presetRules(presetId: string | null): RuleSet | null {
	return presetId === null ? null : (RULESET_PRESET_RULES[presetId] ?? null);
}

function tabOrder(tab: GuideTab): number {
	return tab === 'limit' ? Number.POSITIVE_INFINITY : tab;
}

// `rules` null = every pattern at its default value; otherwise only what scores under them.
export function scoredEntries(rules: RuleSet | null): ScoredEntry[] {
	const out: ScoredEntry[] = [];
	for (const entry of GUIDE_ENTRIES) {
		const info = PATTERN_INFO[entry.pattern];
		let faan = info.faan;
		if (rules) {
			if (!rules.hand_sets.includes(info.handSet)) continue;
			if (entry.pattern === CHICKEN_HAND.name) {
				if (rules.min_faan > 0) continue;
			} else if (rules.faan_overrides[entry.pattern] === 0) continue;
			faan = rules.faan_overrides[entry.pattern] ?? info.faan;
		}
		out.push({
			...entry,
			handSet: info.handSet,
			faan,
			defaultFaan: info.faan,
			limit: info.limit,
			tab: info.limit ? 'limit' : faan
		});
	}
	return out.sort((a, b) => tabOrder(a.tab) - tabOrder(b.tab));
}

export function guideTabs(entries: ScoredEntry[]): GuideTab[] {
	return [...new Set(entries.map((e) => e.tab))];
}

// what the hand pays: a total, limit included, never exceeds the cap
export function paidFaan(entry: ScoredEntry, rules: RuleSet | null): number {
	return rules ? Math.min(entry.faan, rules.faan_cap) : entry.faan;
}

export function matchesQuery(entry: GuideEntry, query: string): boolean {
	const q = query.trim().toLocaleLowerCase();
	if (q === '') return true;
	return [entry.pattern, faanPatternLabel(entry.pattern), entry.description()].some((text) =>
		text.toLocaleLowerCase().includes(q)
	);
}

export interface OverridablePattern {
	pattern: string;
	handSet: HandSet;
	faan: number;
	// GUIDE tab it sits under: its default faan, or 'limit'
	tier: GuideTab;
}

// every scored pattern a custom ruleset's faan_overrides can key, in guide order.
export const OVERRIDABLE_PATTERNS: OverridablePattern[] = scoredEntries(null).map((e) => ({
	pattern: e.pattern,
	handSet: e.handSet,
	faan: e.defaultFaan,
	tier: e.tab
}));
