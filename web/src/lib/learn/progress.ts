import index from './generated/index.json';
import type { IndexEntry } from './generated/lessons';
import {
	loadLearnProgress,
	saveLearnProgress,
	type LearnProgress,
	type LessonProgress
} from '$lib/ui/settings-storage';

export const LESSON_IDS: ReadonlySet<string> = new Set(
	(index as IndexEntry[]).map((lesson) => lesson.id)
);

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

export function solvedCount(progress: LearnProgress, ids: Iterable<string>): number {
	let n = 0;
	for (const id of ids) if (progress[id]?.solved) n++;
	return n;
}

export function loadProgress(): LearnProgress {
	return loadLearnProgress(LESSON_IDS);
}

export function saveAttempt(id: string, correct: boolean): LearnProgress {
	const progress = recordAttempt(loadProgress(), id, correct);
	saveLearnProgress(progress);
	return progress;
}
