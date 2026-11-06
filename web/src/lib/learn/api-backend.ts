// a signed-in player's progress (ADR 0028 "Learn progress: guest vs signed in"): an in-memory
// copy of GET /me/learn; every write updates it and goes to the API, never to localStorage.

import type { Band, PuzzleKind } from './generated/lessons';
import { isBand, isPuzzleKind } from './kinds';
import { LESSON_IDS } from './lessons';
import type { ProgressBackend } from './progress-store';
import * as learnApi from '$lib/net/learn-api';
import type {
	EndlessEntryWire,
	LearnImportWire,
	LearnPrefsWire,
	LearnWire,
	LessonEntryWire
} from '$lib/net/learn-api';
import {
	loadOnboarding,
	type EndlessScore,
	type LearnEndless,
	type LearnProgress,
	type LessonProgress,
	type Onboarding
} from '$lib/ui/settings-storage';

export type LearnApi = Pick<
	typeof learnApi,
	'fetchLearn' | 'putLesson' | 'putEndless' | 'patchPrefs' | 'importLearn'
>;

export function lessonFromWire(wire: LessonEntryWire): LessonProgress {
	const entry: LessonProgress = { solved: wire.solved, attempts: wire.attempts };
	if (wire.solved_at) entry.solvedAt = Date.parse(wire.solved_at);
	if (wire.step !== null && wire.step !== undefined) entry.step = wire.step;
	return entry;
}

export function lessonToWire(entry: LessonProgress): LessonEntryWire {
	return {
		solved: entry.solved,
		attempts: entry.attempts,
		solved_at: entry.solvedAt === undefined ? null : new Date(entry.solvedAt).toISOString(),
		step: entry.step ?? null
	};
}

function scoreToWire({ streak, best, solved }: EndlessScore): EndlessEntryWire {
	return { streak, best, solved };
}

/** The one-time upload: this browser's guest progress. `endless` is null when nothing was ever
 * saved (its band is only a default then). */
export function uploadBody(
	progress: LearnProgress,
	endless: LearnEndless | null,
	onboarding: Onboarding | null
): LearnImportWire {
	const prefs: LearnPrefsWire = {};
	if (endless) prefs.learn_band = endless.band;
	if (onboarding?.coachMarksDone) prefs.coach_marks_done = true;
	return {
		progress: Object.fromEntries(
			Object.entries(progress).map(([id, entry]) => [id, lessonToWire(entry)])
		),
		endless: Object.fromEntries(
			Object.entries(endless?.scores ?? {}).map(([kind, score]) => [kind, scoreToWire(score)])
		),
		prefs
	};
}

/** The server's PUT rule, for a write made before GET /me/learn answered. */
function mergeLesson(server: LessonProgress | undefined, local: LessonProgress): LessonProgress {
	if (!server) return local;
	const solvedAt = [server.solvedAt, local.solvedAt].filter((t) => t !== undefined);
	const merged: LessonProgress = {
		solved: server.solved || local.solved,
		attempts: Math.max(server.attempts, local.attempts)
	};
	if (solvedAt.length) merged.solvedAt = Math.min(...solvedAt);
	if (local.step !== undefined) merged.step = local.step;
	return merged;
}

export class ApiBackend implements ProgressBackend {
	#progress: LearnProgress = {};
	#scores: Partial<Record<PuzzleKind, EndlessScore>> = {};
	#prefs: LearnPrefsWire = {};
	// written before `fill`: the server's copy may predate them
	#written = new Set<string>();
	#writtenKinds = new Set<PuzzleKind>();
	#writtenPrefs: LearnPrefsWire = {};

	constructor(
		private readonly api: LearnApi = learnApi,
		// a failed write stays in memory for this page; the server keeps its last copy
		private readonly onError: (error: unknown) => void = () => {}
	) {}

	fill(wire: LearnWire): void {
		const progress: LearnProgress = {};
		for (const [id, entry] of Object.entries(wire.progress)) progress[id] = lessonFromWire(entry);
		for (const id of this.#written) progress[id] = mergeLesson(progress[id], this.#progress[id]);
		const scores: Partial<Record<PuzzleKind, EndlessScore>> = {};
		for (const [kind, { streak, best, solved }] of Object.entries(wire.endless)) {
			if (isPuzzleKind(kind)) scores[kind] = { streak, best, solved };
		}
		for (const kind of this.#writtenKinds) {
			const local = this.#scores[kind]!;
			const server = scores[kind];
			scores[kind] = server
				? {
						streak: local.streak,
						best: Math.max(server.best, local.best),
						solved: Math.max(server.solved, local.solved)
					}
				: local;
		}
		this.#progress = progress;
		this.#scores = scores;
		this.#prefs = { ...wire.prefs, ...this.#writtenPrefs };
		this.#written.clear();
		this.#writtenKinds.clear();
		this.#writtenPrefs = {};
	}

	progress(): LearnProgress {
		return Object.fromEntries(Object.entries(this.#progress).filter(([id]) => LESSON_IDS.has(id)));
	}

	putLesson(id: string, entry: LessonProgress): void {
		this.#progress = { ...this.#progress, [id]: entry };
		this.#written.add(id);
		this.api.putLesson(id, lessonToWire(entry)).catch(this.onError);
	}

	endless(): LearnEndless {
		const band: Band = isBand(this.#prefs.learn_band) ? this.#prefs.learn_band : 'beginner';
		return { band, scores: { ...this.#scores } };
	}

	putEndlessScore(kind: PuzzleKind, score: EndlessScore): void {
		this.#scores = { ...this.#scores, [kind]: score };
		this.#writtenKinds.add(kind);
		this.api.putEndless(kind, scoreToWire(score)).catch(this.onError);
	}

	putBand(band: Band): void {
		this.#setPrefs({ learn_band: band });
	}

	/** The account's, else this browser's own: a guest who finished the coach marks here
	 * shouldn't see them again just for signing in. */
	onboarding(): Onboarding | null {
		const done = this.#prefs.coach_marks_done;
		return done === undefined ? loadOnboarding() : { coachMarksDone: done };
	}

	putOnboarding(onboarding: Onboarding): void {
		this.#setPrefs({ coach_marks_done: onboarding.coachMarksDone });
	}

	#setPrefs(prefs: LearnPrefsWire): void {
		this.#prefs = { ...this.#prefs, ...prefs };
		this.#writtenPrefs = { ...this.#writtenPrefs, ...prefs };
		this.api.patchPrefs(prefs).catch(this.onError);
	}
}
