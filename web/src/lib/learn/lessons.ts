import index from './generated/index.json';
import type {
	Band,
	IndexEntry,
	Lesson,
	LessonIndexEntry,
	PuzzleTheme,
	SafeReason,
	Track,
	Tutorial,
	TutorialIndexEntry
} from './generated/lessons';
import { BANDS } from './kinds';
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

// one line under each track heading on /learn: what its puzzles ask.
export const TRACK_BLURB: Record<Track, () => string> = {
	basics: m.learn_trackBasicsBlurb,
	waits: m.learn_trackWaitsBlurb,
	efficiency: m.learn_trackEfficiencyBlurb,
	defence: m.learn_trackDefenceBlurb,
	faan: m.learn_trackFaanBlurb
};

export const BAND_LABEL: Record<Band, () => string> = {
	beginner: m.learn_bandBeginner,
	intermediate: m.learn_bandIntermediate,
	advanced: m.learn_bandAdvanced
};

export const SAFE_REASON_LABEL: Record<SafeReason, () => string> = {
	all_copies_visible: m.learn_reasonAllCopiesVisible,
	no_chance: m.learn_reasonNoChance
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

export interface BandGroup {
	band: Band;
	lessons: LessonIndexEntry[];
	/** Ids whose card needs its "Puzzle N" line: another card in the band shares its theme. */
	numbered: ReadonlySet<string>;
}

/** A track's puzzles under `BANDS` order, index order within; tutorials and empty bands dropped. */
export function lessonsByBand(lessons: readonly IndexEntry[]): BandGroup[] {
	return BANDS.map((band) => {
		const inBand = lessons.filter(
			(lesson): lesson is LessonIndexEntry =>
				lesson.lesson_kind === 'puzzle' && lesson.band === band
		);
		const seen = new Map<string, number>();
		for (const lesson of inBand) {
			if (lesson.theme) seen.set(lesson.theme, (seen.get(lesson.theme) ?? 0) + 1);
		}
		const numbered = new Set(
			inBand
				.filter((lesson) => lesson.theme && seen.get(lesson.theme)! > 1)
				.map((lesson) => lesson.id)
		);
		return { band, lessons: inBand, numbered };
	}).filter((group) => group.lessons.length > 0);
}

/** Every lesson in the order /learn lists them, so prev/next walk the index top to bottom. */
export const ORDERED_LESSONS: readonly IndexEntry[] = lessonsByTrack().flatMap(
	(group) => group.lessons
);

export function lessonEntry(id: string): IndexEntry | null {
	return LESSONS.find((lesson) => lesson.id === id) ?? null;
}

export function nextLesson(id: string): IndexEntry | null {
	const i = ORDERED_LESSONS.findIndex((lesson) => lesson.id === id);
	return i === -1 ? null : (ORDERED_LESSONS[i + 1] ?? null);
}

export function previousLesson(id: string): IndexEntry | null {
	const i = ORDERED_LESSONS.findIndex((lesson) => lesson.id === id);
	return i <= 0 ? null : ORDERED_LESSONS[i - 1];
}

export interface TrackPosition {
	track: Track;
	/** 1-based, counting the track's tutorial. */
	n: number;
	total: number;
}

/** Where a lesson sits in its track, in /learn's order; `null` off the index (endless). */
export function trackPosition(
	id: string,
	lessons: readonly IndexEntry[] = ORDERED_LESSONS
): TrackPosition | null {
	const entry = lessons.find((lesson) => lesson.id === id);
	if (!entry) return null;
	const inTrack = lessons.filter((lesson) => lesson.track === entry.track);
	return {
		track: entry.track,
		n: inTrack.indexOf(entry) + 1,
		total: inTrack.length
	};
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
