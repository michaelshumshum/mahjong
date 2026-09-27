// standings/podium placement labels and tones, shared by ScoreSheet and GameEndScreen. Tones
// reference the --color-rank-* tokens rather than duplicating hex values.
import { m } from '$lib/paraglide/messages.js';

const RANK_LABEL_MESSAGES = [m.rank_first, m.rank_second, m.rank_third, m.rank_fourth];

// only seats 0-3 exist in this game, so index 4+ never happens in practice -- kept as a real
// ordinal fallback rather than an assertion, since this indexes off `standings`, not a fixed size.
export function rankLabel(index: number): string {
	return index >= 0 && index < RANK_LABEL_MESSAGES.length
		? RANK_LABEL_MESSAGES[index]()
		: m.rank_nth({ n: index + 1 });
}

export const RANK_TONE: Record<number, string> = {
	0: 'var(--color-rank-gold)',
	1: 'var(--color-rank-silver)',
	2: 'var(--color-rank-bronze)'
};
