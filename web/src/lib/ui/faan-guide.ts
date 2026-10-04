import { m } from '$lib/paraglide/messages.js';
import type { HandSet } from '$lib/net/ruleset';
import type { TileCode } from '$lib/table/tile-code';

export interface GuideEntry {
	pattern: string;
	description: () => string;
	// each string is one group (meld, pair, ...) of concatenated tile codes; empty = no tile example
	example: string[];
}

export type GuideTab = number | 'limit';

export const GUIDE_TABS: GuideTab[] = [1, 2, 3, 4, 5, 6, 7, 8, 'limit'];

const TILE_RE = /[1-9][mps]|[zf][1-9]/g;

export function parseGroup(group: string): TileCode[] {
	return (group.match(TILE_RE) ?? []) as TileCode[];
}

export const GUIDE: Record<string, GuideEntry[]> = {
	'1': [
		{
			pattern: '平糊',
			description: m.guide_descAllSequences,
			example: ['1m2m3m', '4p5p6p', '7p8p9p', '2s3s4s', '8m8m']
		},
		{
			pattern: '門風',
			description: m.guide_descSeatWind,
			example: ['z1z1z1']
		},
		{
			pattern: '圈風',
			description: m.guide_descPrevailingWind,
			example: ['z2z2z2']
		},
		{
			pattern: '箭刻',
			description: m.guide_descDragonPung,
			example: ['z5z5z5']
		},
		{ pattern: '座位花', description: m.guide_descSeatFlower, example: ['f1'] },
		{ pattern: '無花', description: m.guide_descNoFlowers, example: [] },
		{ pattern: '自摸', description: m.guide_descSelfDraw, example: [] },
		{ pattern: '門前清', description: m.guide_descFullyConcealed, example: [] },
		{
			pattern: '一般高',
			description: m.guide_descTwoIdenticalSequences,
			example: ['4s5s6s', '4s5s6s']
		},
		{ pattern: '雞糊', description: m.guide_descChickenHand, example: [] },
		{ pattern: '海底撈月', description: m.guide_descWinOnLastWallTile, example: [] },
		{ pattern: '河底撈魚', description: m.guide_descWinOnLastDiscard, example: [] },
		{ pattern: '槓上開花', description: m.guide_descWinOnKongReplacement, example: [] },
		{ pattern: '搶槓', description: m.guide_descRobbingTheKong, example: [] }
	],
	'2': [
		{
			pattern: '缺一門',
			description: m.guide_descVoidedSuit,
			example: ['1m2m3m', '7m8m9m', '4s5s6s', '2s2s2s', '9s9s']
		},
		{
			pattern: '三暗刻',
			description: m.guide_descThreeConcealedPungs,
			example: ['3m3m3m', '6p6p6p', '9s9s9s', '1p2p3p', '5m5m']
		},
		{ pattern: '全求人', description: m.guide_descAllRevealed, example: [] },
		{
			pattern: '雙箭',
			description: m.guide_descTwoDragonPungs,
			example: ['z5z5z5', 'z6z6z6', '2p3p4p', '7s8s9s', '4m4m']
		},
		{
			pattern: '三步高',
			description: m.guide_descThreeStepSequences,
			example: ['1m2m3m', '3m4m5m', '5m6m7m']
		}
	],
	'3': [
		{
			pattern: '對對糊',
			description: m.guide_descAllPungs,
			example: ['2m2m2m', '5p5p5p', '8s8s8s', 'z3z3z3', '6m6m']
		},
		{
			pattern: '混一色',
			description: m.guide_descHalfFlush,
			example: ['1p2p3p', '4p5p6p', '9p9p9p', 'z5z5z5', 'z1z1']
		},
		{
			pattern: '小三元',
			description: m.guide_descSmallThreeDragons,
			example: ['z5z5z5', 'z6z6z6', 'z7z7', '3s4s5s', '2m2m2m']
		},
		{
			pattern: '混么九',
			description: m.guide_descMixedTerminals,
			example: ['1m1m1m', '9p9p9p', '1s1s1s', 'z4z4z4', 'z7z7']
		},
		{
			pattern: '正花',
			description: m.guide_descFlowerSet,
			example: ['f1f2f3f4']
		}
	],
	'4': [
		{
			pattern: '七對子',
			description: m.guide_descSevenPairs,
			example: ['2m2m', '5m5m', '3p3p', '8p8p', '1s1s', '6s6s', 'z6z6']
		}
	],
	'5': [
		{
			pattern: '小四喜',
			description: m.guide_descSmallFourWinds,
			example: ['z1z1z1', 'z2z2z2', 'z3z3z3', 'z4z4', '4p5p6p']
		}
	],
	'6': [
		{
			pattern: '清一色',
			description: m.guide_descFullFlush,
			example: ['1s2s3s', '4s5s6s', '7s8s9s', '3s3s3s', '5s5s']
		},
		{
			pattern: '三般高',
			description: m.guide_descThreeIdenticalSequences,
			example: ['2p3p4p', '2p3p4p', '2p3p4p', '6m6m6m', '9s9s']
		},
		{
			pattern: '四步高',
			description: m.guide_descFourStepSequences,
			example: ['1p2p3p', '3p4p5p', '5p6p7p', '7p8p9p', '2s2s']
		}
	],
	'7': [
		{
			pattern: '大三元',
			description: m.guide_descBigThreeDragons,
			example: ['z5z5z5', 'z6z6z6', 'z7z7z7', '4m5m6m', '8s8s']
		}
	],
	'8': [
		{
			pattern: '大四喜',
			description: m.guide_descBigFourWinds,
			example: ['z1z1z1', 'z2z2z2', 'z3z3z3', 'z4z4z4', '5s5s']
		}
	],
	limit: [
		{
			pattern: '十三么',
			description: m.guide_descThirteenOrphans,
			example: ['1m9m1p9p1s9sz1z2z3z4z5z6z7z7']
		},
		{
			pattern: '字一色',
			description: m.guide_descAllHonors,
			example: ['z1z1z1', 'z3z3z3', 'z5z5z5', 'z7z7z7', 'z2z2']
		},
		{
			pattern: '清么九',
			description: m.guide_descAllTerminals,
			example: ['1m1m1m', '9m9m9m', '1p1p1p', '9s9s9s', '1s1s']
		},
		{
			pattern: '九蓮寶燈',
			description: m.guide_descNineGates,
			example: ['1p1p1p2p3p4p5p6p7p8p9p9p9p', '5p']
		},
		{ pattern: '天糊', description: m.guide_descHeavenlyHand, example: [] },
		{ pattern: '地糊', description: m.guide_descEarthlyHand, example: [] }
	]
};

const NEW_6 = ['混么九', '雞糊', '海底撈月', '河底撈魚', '槓上開花', '搶槓'];
const NEW_18 = ['七對子', '三暗刻', '全求人', '雙箭', '一般高', '三般高', '三步高', '四步高'];

export function handSetOf(pattern: string): HandSet {
	return NEW_6.includes(pattern) ? 'NEW_6' : NEW_18.includes(pattern) ? 'NEW_18' : 'CLASSIC';
}

// mirrors server RULESET_PRESETS' hand_sets/min_faan; update both together
export const GUIDE_PRESET_RULES: Record<string, { handSets: HandSet[]; minFaan: number }> = {
	hk_classic: { handSets: ['CLASSIC', 'NEW_6', 'NEW_18'], minFaan: 3 },
	hk_casual: { handSets: ['CLASSIC', 'NEW_6', 'NEW_18'], minFaan: 1 },
	hk_strict: { handSets: ['CLASSIC', 'NEW_6'], minFaan: 5 }
};

export function inPreset(pattern: string, presetId: string | null): boolean {
	if (presetId === null) return true;
	const rules = GUIDE_PRESET_RULES[presetId];
	if (!rules) return true;
	if (pattern === '雞糊' && rules.minFaan > 0) return false;
	return rules.handSets.includes(handSetOf(pattern));
}

export function guideEntries(tab: GuideTab, presetId: string | null = null): GuideEntry[] {
	return (GUIDE[String(tab)] ?? []).filter((e) => inPreset(e.pattern, presetId));
}
