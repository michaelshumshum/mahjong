import type { PuzzleKind } from './generated/lessons';

/** A player's answer to one puzzle, shaped per kind. Tiles are `TileCode`s, as in the key. */
export type Answer =
	| { kind: Extract<PuzzleKind, 'best_discard' | 'safe_discard'>; tile: string }
	| { kind: Extract<PuzzleKind, 'winning_tiles'>; tiles: readonly string[] }
	| { kind: Extract<PuzzleKind, 'count_faan'>; faan: number };

/** `partial`: a `winning_tiles` pick that is right as far as it goes but misses some waits. */
export type GradeResult = 'correct' | 'partial' | 'wrong';

export interface Grade {
	result: GradeResult;
}
