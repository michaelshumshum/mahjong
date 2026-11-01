// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Source of truth: server/app/lessons/ (docs/protocol.md §6).

import type { Seat, ServerEvent, StateSync, WinType } from '$lib/net/protocol';

export type LessonKind = 'puzzle' | 'tutorial';
export type PuzzleKind = 'winning_tiles' | 'best_discard' | 'count_faan' | 'safe_discard';
export type Track = 'basics' | 'waits' | 'efficiency' | 'defence' | 'faan';
export type Band = 'beginner' | 'intermediate' | 'advanced';
export type SafeReason = 'all_copies_visible' | 'no_chance';
export type PuzzleTheme =
	| 'too_cheap'
	| 'dead_wait'
	| 'many_sided'
	| 'two_sided'
	| 'pair_wait'
	| 'single_wait'
	| 'edge_closed'
	| 'mixed_wait'
	| 'wider_wait'
	| 'reach_ready'
	| 'trim_run'
	| 'cut_terminal'
	| 'keep_two_sided'
	| 'cut_floater'
	| 'break_pair'
	| 'most_tiles'
	| 'walled_runs'
	| 'dead_honour'
	| 'all_visible'
	| 'limit_hand'
	| 'full_flush'
	| 'half_flush_pungs'
	| 'half_flush_honours'
	| 'half_flush'
	| 'all_pungs'
	| 'all_chows'
	| 'flowers'
	| 'small_faan';
export type StepKind = 'narrate' | 'expect' | 'auto';
export type Highlight = 'hand' | 'discards' | 'claim' | 'wall' | 'melds' | 'hub';

export interface WaitOption {
	tile: string;
	discard_faan: number;
	discard_wins: boolean;
	self_draw_faan: number;
	self_draw_wins: boolean;
	live: number;
}

export interface WinningTilesKey {
	correct: string[];
	below_minimum: string[];
	dead: string[];
	options: WaitOption[];
}

export interface DiscardOption {
	tile: string;
	shanten: number;
	kinds: number;
	tiles: number;
}

export interface BestDiscardKey {
	correct: string[];
	options: DiscardOption[];
}

export interface FaanLine {
	pattern: string;
	faan: number;
}

export interface CountFaanKey {
	correct: number;
	win_type: WinType;
	breakdown: FaanLine[];
	points: number;
}

export interface SafeOption {
	tile: string;
	deals_in_to: number[];
	reasons: SafeReason[];
}

export interface SafeDiscardKey {
	correct: string[];
	reason: SafeReason;
	safe: string[];
	options: SafeOption[];
}

export interface LessonIndexEntry {
	id: string;
	lesson_kind: 'puzzle';
	kind: PuzzleKind;
	track: Track;
	band: Band;
	text: string;
	n: number;
	theme: PuzzleTheme | null;
}

export interface TutorialIndexEntry {
	id: string;
	lesson_kind: 'tutorial';
	track: Track;
	band: Band;
	text: string;
	n: number;
}

export type IndexEntry = LessonIndexEntry | TutorialIndexEntry;

export type Lesson = LessonIndexEntry & {
	engine_version: string;
	snapshot: StateSync;
} & (
		| { kind: 'winning_tiles'; key: WinningTilesKey }
		| { kind: 'best_discard'; key: BestDiscardKey }
		| { kind: 'count_faan'; key: CountFaanKey }
		| { kind: 'safe_discard'; key: SafeDiscardKey }
	);

export type TutorialStep =
	| { kind: 'narrate'; text: string; highlight: Highlight | null }
	| {
			kind: 'expect';
			text: string;
			snapshot: StateSync;
			action: Record<string, unknown>;
			frames: ServerEvent[];
	  }
	| { kind: 'auto'; seat: Seat; action: Record<string, unknown>; frames: ServerEvent[] };

export type Tutorial = TutorialIndexEntry & {
	engine_version: string;
	start: StateSync;
	steps: TutorialStep[];
};
