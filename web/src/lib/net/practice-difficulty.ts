// ascending, the practice dialog's cycle order; no T0 (docs/bots.md §2/§6). mirrors
// server/app/main.py's _PRACTICE_BOT_TIERS. kept out of lobby.ts, which pulls in $env.
export const PRACTICE_DIFFICULTIES = ['easy', 'normal', 'expert', 'impossible'] as const;
export type PracticeDifficulty = (typeof PRACTICE_DIFFICULTIES)[number];
