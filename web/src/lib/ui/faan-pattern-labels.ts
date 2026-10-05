import { m } from '$lib/paraglide/messages.js';

// hand_end.faan_breakdown keys are patterns.py's canonical Chinese names, passed through
// untranslated by live-view.ts; mock fixtures' English literals fall through unchanged below.
export const FAAN_PATTERN_LABEL: Record<string, () => string> = {
	平糊: m.faanPattern_allSequences,
	對對糊: m.faanPattern_allPungs,
	混一色: m.faanPattern_halfFlush,
	清一色: m.faanPattern_fullFlush,
	無花: m.faanPattern_noFlowers,
	自摸: m.faanPattern_selfDraw,
	門前清: m.faanPattern_fullyConcealed,
	門風: m.faanPattern_seatWind,
	圈風: m.faanPattern_prevailingWind,
	箭刻: m.faanPattern_dragonPung,
	小三元: m.faanPattern_smallThreeDragons,
	大三元: m.faanPattern_bigThreeDragons,
	小四喜: m.faanPattern_smallFourWinds,
	大四喜: m.faanPattern_bigFourWinds,
	花么九: m.faanPattern_mixedTerminals,
	海底撈月: m.faanPattern_winOnLastWallTile,
	槓上開花: m.faanPattern_winOnKongReplacement,
	搶槓: m.faanPattern_robbingTheKong,
	正花: m.faanPattern_seatFlower,
	一台花: m.faanPattern_flowerSet,
	連槓開花: m.faanPattern_chainedKong,
	字一色: m.faanPattern_allHonors,
	清么九: m.faanPattern_allTerminals,
	九蓮寶燈: m.faanPattern_nineGates,
	十三么: m.faanPattern_thirteenOrphans,
	天糊: m.faanPattern_heavenlyHand,
	地糊: m.faanPattern_earthlyHand,
	雞糊: m.faanPattern_chickenHand,
	七對子: m.faanPattern_sevenPairs,
	四暗刻: m.faanPattern_fourConcealedPungs,
	十八羅漢: m.faanPattern_eighteenArhats
};

export function faanPatternLabel(name: string): string {
	return (FAAN_PATTERN_LABEL[name] ?? (() => name))();
}
