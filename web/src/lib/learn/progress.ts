import type { IndexEntry } from './generated/lessons';
import { ORDERED_LESSONS, type IndexTab } from './lessons';
import { progressStore } from './progress-store';
import type { LearnProgress, LessonProgress } from '$lib/ui/settings-storage';

/** One graded answer. A solved lesson stays solved, and keeps its first `solvedAt`. */
export function recordAttempt(
	progress: LearnProgress,
	id: string,
	correct: boolean,
	now: number = Date.now()
): LearnProgress {
	const prev: LessonProgress = progress[id] ?? { solved: false, attempts: 0 };
	const next: LessonProgress = { ...prev, attempts: prev.attempts + 1 };
	if (correct && !prev.solved) {
		next.solved = true;
		next.solvedAt = now;
	}
	return { ...progress, [id]: next };
}

/** A tutorial's resume point; `null` clears it (a restart, or the end reached). */
export function recordTutorialStep(
	progress: LearnProgress,
	id: string,
	step: number | null
): LearnProgress {
	const next: LessonProgress = {
		...(progress[id] ?? { solved: false, attempts: 0 })
	};
	if (step === null) delete next.step;
	else next.step = step;
	return { ...progress, [id]: next };
}

export function solvedCount(progress: LearnProgress, ids: Iterable<string>): number {
	let n = 0;
	for (const id of ids) if (progress[id]?.solved) n++;
	return n;
}

/** The first lesson not yet solved, in /learn's order; `null` once every one is. */
export function firstUnsolved(
	progress: LearnProgress,
	lessons: readonly IndexEntry[] = ORDERED_LESSONS
): IndexEntry | null {
	return lessons.find((lesson) => !progress[lesson.id]?.solved) ?? null;
}

/** The tab /learn opens on without `?track=`: the first unsolved lesson's, endless once all are solved. */
export function continueTab(
	progress: LearnProgress,
	lessons: readonly IndexEntry[] = ORDERED_LESSONS
): IndexTab {
	return firstUnsolved(progress, lessons)?.track ?? 'endless';
}

/** The first unsolved lesson after `id` in /learn's order, wrapping round, never `id` itself. */
export function nextUnsolved(
	progress: LearnProgress,
	id: string,
	lessons: readonly IndexEntry[] = ORDERED_LESSONS
): IndexEntry | null {
	const i = lessons.findIndex((lesson) => lesson.id === id);
	const order = [...lessons.slice(i + 1), ...lessons.slice(0, Math.max(i, 0))];
	return order.find((lesson) => lesson.id !== id && !progress[lesson.id]?.solved) ?? null;
}

export function loadProgress(): LearnProgress {
	return progressStore().progress();
}

function save(progress: LearnProgress, id: string): LearnProgress {
	progressStore().putLesson(id, progress[id]);
	return progress;
}

export function saveAttempt(id: string, correct: boolean): LearnProgress {
	return save(recordAttempt(loadProgress(), id, correct), id);
}

export function saveTutorialStep(id: string, step: number | null): LearnProgress {
	return save(recordTutorialStep(loadProgress(), id, step), id);
}

/** The end of a tutorial: solved, with no resume point left. */
export function saveTutorialDone(id: string): LearnProgress {
	return save(recordTutorialStep(recordAttempt(loadProgress(), id, true), id, null), id);
}
