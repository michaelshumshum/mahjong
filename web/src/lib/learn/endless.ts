// endless puzzles (ADR 0025 phase 4): GET /lessons/random returns a generated `Lesson` file's
// shape (docs/protocol.md §10), so the page plays it like a curated one.

import { apiBaseUrl } from '$lib/net/lobby';
import { m } from '$lib/paraglide/messages.js';
import {
	loadLearnEndless,
	saveLearnEndless,
	type EndlessScore,
	type LearnEndless
} from '$lib/ui/settings-storage';
import type { Band, Lesson, PuzzleKind } from './generated/lessons';
import type { GradeResult } from './types';

/** How many recent puzzle ids are sent as `exclude`; the server accepts up to 50. */
export const ENDLESS_RECENT = 20;

export const ENDLESS_TITLE: Record<PuzzleKind, () => string> = {
	winning_tiles: m.learn_endlessTitleWinningTiles,
	best_discard: m.learn_endlessTitleBestDiscard,
	safe_discard: m.learn_endlessTitleSafeDiscard,
	count_faan: m.learn_endlessTitleCountFaan
};

export type EndlessFetch =
	| { ok: true; lesson: Lesson }
	| { ok: false; error: 'rate_limited'; retryAfterS: number | null }
	| { ok: false; error: 'unavailable' };

export interface EndlessRequest {
	kind: PuzzleKind;
	band: Band;
	exclude: readonly string[];
}

export function endlessUrl({ kind, band, exclude }: EndlessRequest, baseUrl: string): string {
	const params = new URLSearchParams({ kind, band });
	for (const id of exclude) params.append('exclude', id);
	return `${baseUrl}/lessons/random?${params}`;
}

/** Never throws: a network error, a non-2xx or a puzzle of the wrong kind is `unavailable`. */
export async function fetchRandomLesson(
	request: EndlessRequest,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<EndlessFetch> {
	try {
		const response = await fetchFn(endlessUrl(request, baseUrl));
		if (response.status === 429) {
			const retryAfter = Number.parseInt(response.headers.get('Retry-After') ?? '', 10);
			return {
				ok: false,
				error: 'rate_limited',
				retryAfterS: Number.isFinite(retryAfter) ? retryAfter : null
			};
		}
		if (!response.ok) return { ok: false, error: 'unavailable' };
		const lesson = (await response.json()) as Lesson;
		if (lesson.lesson_kind !== 'puzzle' || lesson.kind !== request.kind) {
			return { ok: false, error: 'unavailable' };
		}
		return { ok: true, lesson };
	} catch {
		return { ok: false, error: 'unavailable' };
	}
}

/** The newest `ENDLESS_RECENT` ids, oldest first. */
export function rememberRecent(recent: readonly string[], id: string): string[] {
	return [...recent.filter((r) => r !== id), id].slice(-ENDLESS_RECENT);
}

export const EMPTY_SCORE: EndlessScore = { streak: 0, best: 0, solved: 0 };

/** One graded answer. The streak counts puzzles solved with no miss: any miss (a partial pick
 * included) ends it, and a later solve of that puzzle counts as solved only. */
export function recordEndlessAnswer(
	score: EndlessScore,
	result: GradeResult,
	missedBefore: boolean
): EndlessScore {
	if (result !== 'correct') return { ...score, streak: 0 };
	const streak = missedBefore ? score.streak : score.streak + 1;
	return { streak, best: Math.max(score.best, streak), solved: score.solved + 1 };
}

/** Moving on without solving ends the streak. */
export function recordEndlessSkip(score: EndlessScore): EndlessScore {
	return { ...score, streak: 0 };
}

export function endlessScore(endless: LearnEndless, kind: PuzzleKind): EndlessScore {
	return endless.scores[kind] ?? EMPTY_SCORE;
}

/** Loads, updates one kind's score and saves; returns the new score. */
export function saveEndlessScore(
	kind: PuzzleKind,
	update: (score: EndlessScore) => EndlessScore
): EndlessScore {
	const endless = loadLearnEndless();
	const next = update(endlessScore(endless, kind));
	saveLearnEndless({ ...endless, scores: { ...endless.scores, [kind]: next } });
	return next;
}

export function saveEndlessBand(band: Band): void {
	saveLearnEndless({ ...loadLearnEndless(), band });
}
