// hand-written mirror of server/mahjong_core/config.py's RuleSet (not proto-generated -- plain JSON on POST /tables).
// field names/enum values must match RuleSet.to_dict() exactly -- a mismatch silently falls back to hk_classic server-side.

import { m } from '$lib/paraglide/messages.js';

export type ScoreTable = 'full_spicy' | 'half_spicy';
export type HandSet = 'CLASSIC' | 'NEW_6' | 'NEW_18';
export type DiscardPayment = 'all' | 'half';
export type GameLength = 'EAST_ONLY' | 'EAST_SOUTH' | 'FULL';

export interface RuleSet {
	min_faan: number;
	faan_cap: number;
	score_table: ScoreTable;
	hand_sets: HandSet[];
	faan_overrides: Record<string, number>;
	discard_payment: DiscardPayment;
	self_draw_multiplier: number;
	flowers_score: boolean;
	seven_flowers_instant_win: boolean;
	eight_flowers_instant_win: boolean;
	thirteen_orphans_wait_bonus: boolean;
	game_length: GameLength;
	dealer_repeat_on_win: boolean;
	dealer_repeat_on_draw: boolean;
	wall_reserve: number;
	four_kong_abort: boolean;
	nine_terminals_abort: boolean;
	tenpai_payments: boolean;
	// multi_win stays in the type (to_dict() requires every key) but CreateTableDialog never binds an input to it --
	// server rejects `True` outright, and a togglable field it can't honor would silently discard the ruleset.
	multi_win: boolean;
	flowers_enabled: boolean;
	kong_rob_enabled: boolean;
	concealed_kong_robbable: boolean;
	pao_rules: boolean;
	provable_fairness: boolean;
	// server-enforced timing
	turn_seconds: number;
	claim_seconds: number;
	hand_end_seconds: number;
	turn_timeout_strikes: number;
	disconnect_grace_seconds: number;
}

// RuleSet()'s field defaults -- the starting point CreateTableDialog prefills the custom form
// with, and what hk_classic resolves to.
export const DEFAULT_RULESET: RuleSet = {
	min_faan: 3,
	faan_cap: 10,
	score_table: 'half_spicy',
	hand_sets: ['CLASSIC', 'NEW_6'],
	faan_overrides: {},
	discard_payment: 'all',
	self_draw_multiplier: 1.5,
	flowers_score: true,
	seven_flowers_instant_win: false,
	eight_flowers_instant_win: false,
	thirteen_orphans_wait_bonus: false,
	game_length: 'EAST_ONLY',
	dealer_repeat_on_win: true,
	dealer_repeat_on_draw: true,
	wall_reserve: 0,
	four_kong_abort: false,
	nine_terminals_abort: false,
	tenpai_payments: false,
	multi_win: false,
	flowers_enabled: true,
	kong_rob_enabled: true,
	concealed_kong_robbable: false,
	pao_rules: false,
	provable_fairness: false,
	turn_seconds: 15,
	claim_seconds: 5,
	hand_end_seconds: 10,
	turn_timeout_strikes: 3,
	disconnect_grace_seconds: 20
};

export const VALID_MIN_FAAN = [0, 1, 3, 5] as const;
export const VALID_FAAN_CAP = [8, 10, 13] as const;
export const HAND_SET_OPTIONS: { value: HandSet; label: () => string }[] = [
	{ value: 'CLASSIC', label: m.ruleset_handSetClassic },
	{ value: 'NEW_6', label: m.ruleset_handSetNew6 },
	{ value: 'NEW_18', label: m.ruleset_handSetNew18 }
];

// named presets a client can pick without knowing their field values -- deliberately not a local
// copy of the real RuleSet values, which POST /tables resolves server-side from `id` alone.
export interface RulesetPresetOption {
	id: string;
	label: () => string;
	description: () => string;
}

export const RULESET_PRESET_OPTIONS: RulesetPresetOption[] = [
	{
		id: 'hk_classic',
		label: m.ruleset_presetHkClassicLabel,
		description: m.ruleset_presetHkClassicDescription
	},
	{
		id: 'hk_casual',
		label: m.ruleset_presetHkCasualLabel,
		description: m.ruleset_presetHkCasualDescription
	},
	{
		id: 'hk_strict',
		label: m.ruleset_presetHkStrictLabel,
		description: m.ruleset_presetHkStrictDescription
	}
];

export const DEFAULT_PRESET_ID = 'hk_classic';
export const CUSTOM_PRESET_ID = 'custom';

// mirrors server mahjong_core/presets.py's RULESET_PRESETS; update both together. used only to
// seed the custom editor and the faan guide's filter -- named presets still post by id alone.
export const RULESET_PRESET_RULES: Record<string, RuleSet> = {
	hk_classic: DEFAULT_RULESET,
	hk_casual: {
		...DEFAULT_RULESET,
		min_faan: 1,
		faan_cap: 13,
		score_table: 'full_spicy',
		hand_sets: ['CLASSIC', 'NEW_6', 'NEW_18']
	},
	hk_strict: { ...DEFAULT_RULESET, min_faan: 5, discard_payment: 'half' }
};

// no server reader (docs/rules.md §10) -- the custom editor never shows them and always sends
// the defaults, so a toggle can't promise a rule the engine ignores.
export const INERT_RULE_FIELDS = [
	'self_draw_multiplier',
	'thirteen_orphans_wait_bonus',
	'four_kong_abort',
	'nine_terminals_abort',
	'tenpai_payments',
	'multi_win',
	'pao_rules'
] as const satisfies readonly (keyof RuleSet)[];

type NumericRuleField =
	| 'wall_reserve'
	| 'turn_seconds'
	| 'claim_seconds'
	| 'hand_end_seconds'
	| 'turn_timeout_strikes'
	| 'disconnect_grace_seconds';

// lower bounds match what the server can run; it validates almost none of them and an invalid
// custom body silently becomes hk_classic, so the editor blocks submit instead.
export const NUMERIC_RULE_MIN: Record<NumericRuleField, number> = {
	wall_reserve: 0,
	turn_seconds: 1,
	claim_seconds: 1,
	hand_end_seconds: 0,
	turn_timeout_strikes: 1,
	disconnect_grace_seconds: 0
};

export const FAAN_OVERRIDE_MAX = 13;

export function isValidRuleNumber(field: NumericRuleField, value: unknown): boolean {
	return typeof value === 'number' && Number.isInteger(value) && value >= NUMERIC_RULE_MIN[field];
}

export function isValidFaanOverride(value: unknown): boolean {
	return (
		typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= FAAN_OVERRIDE_MAX
	);
}

export function invalidRuleFields(rules: RuleSet): string[] {
	const invalid: string[] = (Object.keys(NUMERIC_RULE_MIN) as NumericRuleField[]).filter(
		(field) => !isValidRuleNumber(field, rules[field])
	);
	if (rules.hand_sets.length === 0) invalid.push('hand_sets');
	for (const [pattern, value] of Object.entries(rules.faan_overrides)) {
		if (!isValidFaanOverride(value)) invalid.push(`faan_overrides.${pattern}`);
	}
	return invalid;
}

// the body a custom table posts: inert fields pinned to their defaults whatever was stored.
export function withInertDefaults(rules: RuleSet): RuleSet {
	const out = { ...rules };
	for (const field of INERT_RULE_FIELDS)
		(out as Record<string, unknown>)[field] = DEFAULT_RULESET[field];
	return out;
}

function sameValue(a: unknown, b: unknown): boolean {
	if (Array.isArray(a) && Array.isArray(b)) {
		return a.length === b.length && a.every((v) => b.includes(v));
	}
	return a === b;
}

// how many visible rules differ from `base`; each faan override counts as one.
export function countRuleChanges(rules: RuleSet, base: RuleSet): number {
	const inert: readonly string[] = INERT_RULE_FIELDS;
	let changes = 0;
	for (const key of Object.keys(DEFAULT_RULESET) as (keyof RuleSet)[]) {
		if (key === 'faan_overrides' || inert.includes(key)) continue;
		if (!sameValue(rules[key], base[key])) changes++;
	}
	const keys = new Set([...Object.keys(rules.faan_overrides), ...Object.keys(base.faan_overrides)]);
	for (const key of keys) {
		if (rules.faan_overrides[key] !== base.faan_overrides[key]) changes++;
	}
	return changes;
}

const ENUM_VALUES: Partial<Record<keyof RuleSet, readonly unknown[]>> = {
	min_faan: VALID_MIN_FAAN,
	faan_cap: VALID_FAAN_CAP,
	score_table: ['full_spicy', 'half_spicy'],
	discard_payment: ['all', 'half'],
	game_length: ['EAST_ONLY', 'EAST_SOUTH', 'FULL']
};

// a stored ruleset -> a usable one: every field type-checked, anything off reverts to default.
export function sanitizeRuleSet(value: unknown): RuleSet {
	const out: RuleSet = { ...DEFAULT_RULESET, faan_overrides: {} };
	if (typeof value !== 'object' || value === null) return out;
	const v = value as Record<string, unknown>;
	for (const key of Object.keys(DEFAULT_RULESET) as (keyof RuleSet)[]) {
		const candidate = v[key];
		const fallback = DEFAULT_RULESET[key];
		if (key === 'hand_sets') {
			const sets = HAND_SET_OPTIONS.map((o) => o.value);
			if (Array.isArray(candidate) && candidate.every((s) => sets.includes(s))) {
				out.hand_sets = [...new Set(candidate as HandSet[])];
			}
		} else if (key === 'faan_overrides') {
			if (typeof candidate === 'object' && candidate !== null && !Array.isArray(candidate)) {
				out.faan_overrides = Object.fromEntries(
					Object.entries(candidate).filter(([, n]) => isValidFaanOverride(n))
				) as Record<string, number>;
			}
		} else if (typeof candidate === typeof fallback) {
			const allowed = ENUM_VALUES[key];
			if (!allowed || allowed.includes(candidate)) {
				(out as unknown as Record<string, unknown>)[key] = candidate;
			}
		}
	}
	return withInertDefaults(out);
}
