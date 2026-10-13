import { describe, expect, it } from 'vitest';
import {
	DEFAULT_RULESET,
	INERT_RULE_FIELDS,
	RULESET_PRESET_OPTIONS,
	RULESET_PRESET_RULES,
	countRuleChanges,
	invalidRuleFields,
	sanitizeRuleSet,
	withInertDefaults,
	type RuleSet
} from './ruleset';

const classic = (): RuleSet => ({ ...DEFAULT_RULESET, faan_overrides: {} });

describe('RULESET_PRESET_RULES', () => {
	it('covers every named preset', () => {
		expect(Object.keys(RULESET_PRESET_RULES).sort()).toEqual(
			RULESET_PRESET_OPTIONS.map((o) => o.id).sort()
		);
	});

	it('mirrors server presets.py', () => {
		expect(countRuleChanges(RULESET_PRESET_RULES.hk_classic, DEFAULT_RULESET)).toBe(0);
		expect(RULESET_PRESET_RULES.hk_casual).toMatchObject({
			min_faan: 1,
			faan_cap: 13,
			score_table: 'full_spicy',
			hand_sets: ['CLASSIC', 'NEW_6', 'NEW_18']
		});
		expect(RULESET_PRESET_RULES.hk_strict).toMatchObject({ min_faan: 5, discard_payment: 'half' });
	});
});

describe('countRuleChanges', () => {
	it('counts differing visible fields and each faan override', () => {
		const rules = { ...classic(), min_faan: 1, faan_overrides: { 平糊: 2, 自摸: 0 } };
		expect(countRuleChanges(rules, DEFAULT_RULESET)).toBe(3);
	});

	it('ignores hand set order', () => {
		const rules = { ...classic(), hand_sets: ['NEW_6', 'CLASSIC'] as RuleSet['hand_sets'] };
		expect(countRuleChanges(rules, DEFAULT_RULESET)).toBe(0);
	});

	it('ignores inert fields', () => {
		const rules = { ...classic(), pao_rules: true, self_draw_multiplier: 3 };
		expect(countRuleChanges(rules, DEFAULT_RULESET)).toBe(0);
	});
});

describe('invalidRuleFields', () => {
	it('accepts the defaults', () => {
		expect(invalidRuleFields(classic())).toEqual([]);
	});

	it('flags empty, fractional and below-minimum numbers', () => {
		const rules = {
			...classic(),
			turn_seconds: null as unknown as number,
			claim_seconds: 1.5,
			wall_reserve: -1
		};
		expect(invalidRuleFields(rules).sort()).toEqual(
			['claim_seconds', 'turn_seconds', 'wall_reserve'].sort()
		);
	});

	it('flags no hand sets and out-of-range overrides', () => {
		const rules = { ...classic(), hand_sets: [], faan_overrides: { 平糊: 14, 自摸: 2 } };
		expect(invalidRuleFields(rules)).toEqual(['hand_sets', 'faan_overrides.平糊']);
	});
});

describe('withInertDefaults', () => {
	it('pins every inert field to its default', () => {
		const rules = withInertDefaults({ ...classic(), multi_win: true, tenpai_payments: true });
		for (const field of INERT_RULE_FIELDS) expect(rules[field]).toBe(DEFAULT_RULESET[field]);
	});
});

describe('sanitizeRuleSet', () => {
	it('keeps valid fields', () => {
		const stored = { ...RULESET_PRESET_RULES.hk_casual, faan_overrides: { 平糊: 2 } };
		expect(sanitizeRuleSet(stored)).toEqual(stored);
	});

	it('reverts wrong types, unknown enum values and bad overrides to defaults', () => {
		const rules = sanitizeRuleSet({
			min_faan: 2,
			score_table: 'mild',
			turn_seconds: '30',
			hand_sets: ['CLASSIC', 'BOGUS'],
			faan_overrides: { 平糊: -1, 自摸: 3 },
			multi_win: true
		});
		expect(rules.min_faan).toBe(DEFAULT_RULESET.min_faan);
		expect(rules.score_table).toBe(DEFAULT_RULESET.score_table);
		expect(rules.turn_seconds).toBe(DEFAULT_RULESET.turn_seconds);
		expect(rules.hand_sets).toEqual(DEFAULT_RULESET.hand_sets);
		expect(rules.faan_overrides).toEqual({ 自摸: 3 });
		expect(rules.multi_win).toBe(false);
	});

	it('falls back to the defaults for a non-object', () => {
		expect(sanitizeRuleSet('nope')).toEqual(classic());
	});
});
