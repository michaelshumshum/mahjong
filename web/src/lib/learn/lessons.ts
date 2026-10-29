import index from './generated/index.json';
import type { Band, Lesson, LessonIndexEntry, Track } from './generated/lessons';
import { m } from '$lib/paraglide/messages.js';

export const LESSONS: readonly LessonIndexEntry[] = index as LessonIndexEntry[];

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

export interface TrackGroup {
	track: Track;
	lessons: LessonIndexEntry[];
}

/** Every track in `TRACKS` order, each with its lessons in index order; empty tracks dropped. */
export function lessonsByTrack(lessons: readonly LessonIndexEntry[] = LESSONS): TrackGroup[] {
	return TRACKS.map((track) => ({
		track,
		lessons: lessons.filter((lesson) => lesson.track === track)
	})).filter((group) => group.lessons.length > 0);
}

// the order /learn lists them in, so prev/next walk the index top to bottom.
const ORDERED: readonly LessonIndexEntry[] = lessonsByTrack().flatMap((group) => group.lessons);

export function lessonEntry(id: string): LessonIndexEntry | null {
	return LESSONS.find((lesson) => lesson.id === id) ?? null;
}

export function nextLesson(id: string): LessonIndexEntry | null {
	const i = ORDERED.findIndex((lesson) => lesson.id === id);
	return i === -1 ? null : (ORDERED[i + 1] ?? null);
}

export function previousLesson(id: string): LessonIndexEntry | null {
	const i = ORDERED.findIndex((lesson) => lesson.id === id);
	return i <= 0 ? null : ORDERED[i - 1];
}

// lazy, so each lesson is its own chunk and /learn ships only the index.
const LESSON_FILES = import.meta.glob<unknown>(['./generated/*.json', '!./generated/index.json'], {
	import: 'default'
});

export async function loadLesson(id: string): Promise<Lesson | null> {
	const load = LESSON_FILES[`./generated/${id}.json`];
	if (!load || lessonEntry(id) === null) return null;
	return (await load()) as Lesson;
}
