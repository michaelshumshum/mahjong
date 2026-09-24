// hand-written mirror of server/mahjong_core/config.py's RuleSet -- not make proto-generated,
// since it's a plain JSON body on POST /tables, not a protocol message. Field names/enum values
// must match RuleSet.to_dict() exactly: a mismatch doesn't error, it silently falls back to
// hk_classic server-side, so CreateTableDialog treats a sent/echoed mismatch as a real bug.

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
	// variants. multi_win stays in the type (RuleSet.to_dict() requires every key) but
	// CreateTableDialog never binds an input to it -- the server rejects `True` outright, and a
	// togglable field it can never honor would silently discard the whole custom ruleset.
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
	hand_sets: ['CLASSIC', 'NEW_6', 'NEW_18'],
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
export const VALID_FAAN_CAP = [10, 13] as const;
export const HAND_SET_OPTIONS: { value: HandSet; label: string }[] = [
	{ value: 'CLASSIC', label: 'Classic' },
	{ value: 'NEW_6', label: 'New 6' },
	{ value: 'NEW_18', label: 'New 18' }
];

// named presets a client can pick without knowing their field values -- deliberately not a local
// copy of the real RuleSet values, which POST /tables resolves server-side from `id` alone.
export interface RulesetPresetOption {
	id: string;
	label: string;
	description: string;
}

export const RULESET_PRESET_OPTIONS: RulesetPresetOption[] = [
	{ id: 'hk_classic', label: 'HK Classic', description: 'min faan 3, faan cap 10' },
	{ id: 'hk_casual', label: 'Casual', description: 'min faan 1, faan cap 13' },
	{ id: 'hk_strict', label: 'Strict', description: 'min faan 5, no New 18, half payment' }
];

export const DEFAULT_PRESET_ID = 'hk_classic';
export const CUSTOM_PRESET_ID = 'custom';
