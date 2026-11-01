import index from './generated/index.json';
import type {
	Band,
	IndexEntry,
	Lesson,
	PuzzleTheme,
	SafeReason,
	Track,
	Tutorial,
	TutorialIndexEntry
} from './generated/lessons';
import { m } from '$lib/paraglide/messages.js';

/** Either generated lesson file: a puzzle or a guided tutorial. */
export type LoadedLesson = Lesson | Tutorial;

export const LESSONS: readonly IndexEntry[] = index as IndexEntry[];

// the generator puts tutorials first, so this is the one a newcomer starts with.
export const FIRST_TUTORIAL: TutorialIndexEntry = LESSONS.find(
	(entry): entry is TutorialIndexEntry => entry.lesson_kind === 'tutorial'
)!;

export const TRACKS = [
	'basics',
	'waits',
	'efficiency',
	'defence',
	'faan'
] as const satisfies readonly Track[];

export const TRACK_LABEL: Record<Track, () => string> = {
	basics: m.learn_trackBasics,
	waits: m.learn_trackWaits,
	efficiency: m.learn_trackEfficiency,
	defence: m.learn_trackDefence,
	faan: m.learn_trackFaan
};

export const BAND_LABEL: Record<Band, () => string> = {
	beginner: m.learn_bandBeginner,
	intermediate: m.learn_bandIntermediate,
	advanced: m.learn_bandAdvanced
};

export const SAFE_REASON_LABEL: Record<SafeReason, () => string> = {
	all_copies_visible: m.learn_reasonAllCopiesVisible,
	no_chance: m.learn_reasonNoChance,
	genbutsu: m.learn_reasonGenbutsu
};

// a mined puzzle's title (docs/frontend.md §7 "Learn"); listed by hand so the messages tree-shake.
export const THEME_LABEL: Record<PuzzleTheme, () => string> = {
	too_cheap: m.learn_themeTooCheap,
	dead_wait: m.learn_themeDeadWait,
	many_sided: m.learn_themeManySided,
	two_sided: m.learn_themeTwoSided,
	pair_wait: m.learn_themePairWait,
	single_wait: m.learn_themeSingleWait,
	edge_closed: m.learn_themeEdgeClosed,
	mixed_wait: m.learn_themeMixedWait,
	wider_wait: m.learn_themeWiderWait,
	reach_ready: m.learn_themeReachReady,
	trim_run: m.learn_themeTrimRun,
	cut_terminal: m.learn_themeCutTerminal,
	keep_two_sided: m.learn_themeKeepTwoSided,
	cut_floater: m.learn_themeCutFloater,
	break_pair: m.learn_themeBreakPair,
	most_tiles: m.learn_themeMostTiles,
	genbutsu: m.learn_themeGenbutsu,
	walled_runs: m.learn_themeWalledRuns,
	dead_honour: m.learn_themeDeadHonour,
	all_visible: m.learn_themeAllVisible,
	limit_hand: m.learn_themeLimitHand,
	full_flush: m.learn_themeFullFlush,
	half_flush_pungs: m.learn_themeHalfFlushPungs,
	half_flush_honours: m.learn_themeHalfFlushHonours,
	half_flush: m.learn_themeHalfFlush,
	all_pungs: m.learn_themeAllPungs,
	all_chows: m.learn_themeAllChows,
	flowers: m.learn_themeFlowers,
	small_faan: m.learn_themeSmallFaan
};

export interface TrackGroup {
	track: Track;
	lessons: IndexEntry[];
}

/** Every track in `TRACKS` order, each with its lessons in index order; empty tracks dropped. */
export function lessonsByTrack(lessons: readonly IndexEntry[] = LESSONS): TrackGroup[] {
	return TRACKS.map((track) => ({
		track,
		lessons: lessons.filter((lesson) => lesson.track === track)
	})).filter((group) => group.lessons.length > 0);
}

// the order /learn lists them in, so prev/next walk the index top to bottom.
const ORDERED: readonly IndexEntry[] = lessonsByTrack().flatMap((group) => group.lessons);

export function lessonEntry(id: string): IndexEntry | null {
	return LESSONS.find((lesson) => lesson.id === id) ?? null;
}

export function nextLesson(id: string): IndexEntry | null {
	const i = ORDERED.findIndex((lesson) => lesson.id === id);
	return i === -1 ? null : (ORDERED[i + 1] ?? null);
}

export function previousLesson(id: string): IndexEntry | null {
	const i = ORDERED.findIndex((lesson) => lesson.id === id);
	return i <= 0 ? null : ORDERED[i - 1];
}

// lazy, so each lesson is its own chunk and /learn ships only the index.
const LESSON_FILES = import.meta.glob<unknown>(['./generated/*.json', '!./generated/index.json'], {
	import: 'default'
});

export async function loadLesson(id: string): Promise<LoadedLesson | null> {
	const load = LESSON_FILES[`./generated/${id}.json`];
	if (!load || lessonEntry(id) === null) return null;
	return (await load()) as LoadedLesson;
}
