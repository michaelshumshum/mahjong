// learn progress, endless scores and learn prefs behind swappable backends; a guest's is
// localStorage (docs/frontend.md §6 "Persistence", ADR 0028 "Learn progress").

import type { Band, PuzzleKind } from './generated/lessons';
import { LESSON_IDS } from './lessons';
import {
	loadLearnEndless,
	loadLearnProgress,
	loadOnboarding,
	saveLearnEndless,
	saveLearnProgress,
	saveOnboarding,
	type EndlessScore,
	type LearnEndless,
	type LearnProgress,
	type LessonProgress,
	type Onboarding
} from '$lib/ui/settings-storage';

/** Reads are synchronous; a write replaces one entry. */
export interface ProgressBackend {
	/** Progress for the generated index's lessons only. */
	progress(): LearnProgress;
	putLesson(id: string, entry: LessonProgress): void;
	endless(): LearnEndless;
	putEndlessScore(kind: PuzzleKind, score: EndlessScore): void;
	putBand(band: Band): void;
	onboarding(): Onboarding | null;
	putOnboarding(onboarding: Onboarding): void;
}

export const localBackend: ProgressBackend = {
	progress: () => loadLearnProgress(LESSON_IDS),
	putLesson(id, entry) {
		saveLearnProgress({ ...loadLearnProgress(LESSON_IDS), [id]: entry });
	},
	endless: loadLearnEndless,
	putEndlessScore(kind, score) {
		const endless = loadLearnEndless();
		saveLearnEndless({ ...endless, scores: { ...endless.scores, [kind]: score } });
	},
	putBand(band) {
		saveLearnEndless({ ...loadLearnEndless(), band });
	},
	onboarding: loadOnboarding,
	putOnboarding: saveOnboarding
};

let backend: ProgressBackend = localBackend;

export function progressStore(): ProgressBackend {
	return backend;
}

export function useProgressBackend(next: ProgressBackend): void {
	backend = next;
}
