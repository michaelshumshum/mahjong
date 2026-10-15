import type { BotTier } from '$lib/net/protocol';
import { m } from '$lib/paraglide/messages.js';

// ascending, the practice dialog's cycle order; no T0 (docs/bots.md §2/§6). mirrors
// server/app/main.py's _PRACTICE_BOT_TIERS. kept out of lobby.ts, which pulls in $env.
export const PRACTICE_DIFFICULTIES = ['easy', 'normal', 'expert', 'impossible'] as const;
export type PracticeDifficulty = (typeof PRACTICE_DIFFICULTIES)[number];

export const PRACTICE_DIFFICULTY_TO_TIER: Record<PracticeDifficulty, BotTier> = {
	easy: 'T1',
	normal: 'T2',
	expert: 'T4',
	impossible: 'ORACLE'
};

export const DIFFICULTY_LABEL: Record<PracticeDifficulty, () => string> = {
	easy: m.practiceDifficultySlot_easyLabel,
	normal: m.practiceDifficultySlot_normalLabel,
	expert: m.practiceDifficultySlot_expertLabel,
	impossible: m.practiceDifficultySlot_impossibleLabel
};

export const TIER_LABEL: Partial<Record<BotTier, () => string>> = Object.fromEntries(
	PRACTICE_DIFFICULTIES.map((d) => [PRACTICE_DIFFICULTY_TO_TIER[d], DIFFICULTY_LABEL[d]])
);
