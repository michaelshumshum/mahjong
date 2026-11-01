import type { Band, PuzzleKind } from './generated/lessons';

/** Every puzzle kind, in the order /learn lists their tracks (waits, efficiency, defence, faan). */
export const PUZZLE_KINDS = [
	'winning_tiles',
	'best_discard',
	'safe_discard',
	'count_faan'
] as const satisfies readonly PuzzleKind[];

export const BANDS = ['beginner', 'intermediate', 'advanced'] as const satisfies readonly Band[];

export function isPuzzleKind(value: unknown): value is PuzzleKind {
	return (PUZZLE_KINDS as readonly unknown[]).includes(value);
}

export function isBand(value: unknown): value is Band {
	return (BANDS as readonly unknown[]).includes(value);
}
