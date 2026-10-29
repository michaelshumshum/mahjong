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

/** One `winning_tiles` tile as the key reads it: clears the minimum, too cheap, dead, or no win. */
export type WaitVerdict = 'wins' | 'below_minimum' | 'dead' | 'no_win';

/** One `safe_discard` tile: safe and deducible (the accepted set), safe by luck, or deals in. */
export type SafeOutcome = 'deducible' | 'lucky' | 'deals_in';

/** One row of `OptionTable`: a tile, whether it is an answer or the pick, and its other cells. */
export interface OptionTableRow {
	tile: string;
	tone: 'good' | 'bad' | 'neutral';
	answer: boolean;
	picked: boolean;
	cells: readonly string[];
}
