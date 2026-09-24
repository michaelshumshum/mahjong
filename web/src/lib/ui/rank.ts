// standings/podium placement labels and tones, shared by ScoreSheet and GameEndScreen. Tones
// reference the --color-rank-* tokens rather than duplicating hex values.
export const RANK_LABEL = ['1st', '2nd', '3rd', '4th'];

export const RANK_TONE: Record<number, string> = {
	0: 'var(--color-rank-gold)',
	1: 'var(--color-rank-silver)',
	2: 'var(--color-rank-bronze)'
};
