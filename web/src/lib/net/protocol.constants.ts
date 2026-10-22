// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Source of truth: server/mahjong_core/config.py, server/mahjong_core/scoring/.

/** Inclusive ranges for a client-supplied custom ruleset (docs/rules.md §10). */
export const CLIENT_RULE_BOUNDS = {
	wall_reserve: { min: 0, max: 30 },
	turn_seconds: { min: 5, max: 60 },
	claim_seconds: { min: 2, max: 30 },
	hand_end_seconds: { min: 3, max: 60 },
	turn_timeout_strikes: { min: 1, max: 10 },
	disconnect_grace_seconds: { min: 5, max: 60 },
	self_draw_multiplier: { min: 1, max: 2 }
} as const;

/** The largest faan a pattern can score, and so the largest faan override. */
export const LIMIT_FAAN = 13;

/** Every scored pattern at its default value, in registry order (docs/rules.md §7). */
export const FAAN_PATTERNS = [
	{ name: '平糊', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '對對糊', handSet: 'CLASSIC', faan: 3, limit: false },
	{ name: '混一色', handSet: 'CLASSIC', faan: 3, limit: false },
	{ name: '清一色', handSet: 'CLASSIC', faan: 7, limit: false },
	{ name: '無花', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '自摸', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '門前清', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '門風', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '圈風', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '箭刻', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '小三元', handSet: 'CLASSIC', faan: 5, limit: false },
	{ name: '大三元', handSet: 'CLASSIC', faan: 8, limit: false },
	{ name: '小四喜', handSet: 'CLASSIC', faan: 6, limit: false },
	{ name: '大四喜', handSet: 'CLASSIC', faan: 13, limit: true },
	{ name: '十八羅漢', handSet: 'CLASSIC', faan: 13, limit: true },
	{ name: '花么九', handSet: 'CLASSIC', faan: 4, limit: false },
	{ name: '海底撈月', handSet: 'NEW_6', faan: 1, limit: false },
	{ name: '槓上開花', handSet: 'NEW_6', faan: 1, limit: false },
	{ name: '搶槓', handSet: 'NEW_6', faan: 1, limit: false },
	{ name: '連槓開花', handSet: 'NEW_6', faan: 8, limit: false },
	{ name: '正花', handSet: 'CLASSIC', faan: 1, limit: false },
	{ name: '一台花', handSet: 'CLASSIC', faan: 2, limit: false },
	{ name: '字一色', handSet: 'CLASSIC', faan: 10, limit: true },
	{ name: '清么九', handSet: 'CLASSIC', faan: 10, limit: true },
	{ name: '九蓮寶燈', handSet: 'CLASSIC', faan: 10, limit: true },
	{ name: '十三么', handSet: 'CLASSIC', faan: 13, limit: true },
	{ name: '天糊', handSet: 'CLASSIC', faan: 13, limit: true },
	{ name: '地糊', handSet: 'CLASSIC', faan: 13, limit: true },
	{ name: '四暗刻', handSet: 'CLASSIC', faan: 8, limit: false },
	{ name: '七對子', handSet: 'NEW_18', faan: 4, limit: false }
] as const;

/** 雞糊: not a registry pattern, scored by faan.py's own fallback. */
export const CHICKEN_HAND = { name: '雞糊', faan: 0 } as const;

/** Points per faan, indexed 0..LIMIT_FAAN (docs/rules.md §8). */
export const POINTS_TABLES = {
	full_spicy: [1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096, 8192],
	half_spicy: [1, 2, 4, 8, 16, 24, 32, 48, 64, 96, 128, 192, 256, 384]
} as const;
