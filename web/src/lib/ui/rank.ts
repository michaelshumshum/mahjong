// standings/podium placement labels and tones, shared by ScoreSheet and GameEndScreen (the
// latter renders the former wholesale -- docs/03-frontend.md's "Game-end summary"). Tones
// reference the --color-rank-* tokens (_tokens.scss) rather than duplicating hex values.
export const RANK_LABEL = ['1st', '2nd', '3rd', '4th'];

export const RANK_TONE: Record<number, string> = {
	0: 'var(--color-rank-gold)',
	1: 'var(--color-rank-silver)',
	2: 'var(--color-rank-bronze)'
};
