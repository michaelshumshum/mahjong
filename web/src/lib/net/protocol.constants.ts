// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Source of truth: server/mahjong_core/config.py, server/mahjong_core/scoring/patterns.py.

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
