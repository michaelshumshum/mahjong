import type { Band } from '$lib/learn/generated/lessons';
import { apiBaseUrl, apiRequest } from './lobby';

// hand-written like account.ts (docs/protocol.md §10 "Accounts"). server: app/api_models.py's
// LessonProgressIn/Out, EndlessScoreIn/Out, LearnResponse, LearnImport, PrefsPatch.
export interface LessonEntryWire {
	solved: boolean;
	attempts: number;
	solved_at?: string | null;
	step?: number | null;
}

export interface EndlessEntryWire {
	streak: number;
	best: number;
	solved: number;
}

export interface LearnPrefsWire {
	learn_band?: Band;
	coach_marks_done?: boolean;
}

export interface LearnWire {
	progress: Record<string, LessonEntryWire & { imported: boolean }>;
	endless: Record<string, EndlessEntryWire & { imported: boolean }>;
	prefs: LearnPrefsWire;
}

export interface LearnImportWire {
	progress: Record<string, LessonEntryWire>;
	endless: Record<string, EndlessEntryWire>;
	prefs: LearnPrefsWire;
}

export async function fetchLearn(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<LearnWire> {
	const response = await apiRequest('GET', '/me/learn', { baseUrl, fetchFn, session: true });
	return (await response.json()) as LearnWire;
}

export async function putLesson(
	id: string,
	entry: LessonEntryWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await apiRequest('PUT', `/me/learn/${encodeURIComponent(id)}`, {
		baseUrl,
		fetchFn,
		body: entry,
		session: true
	});
}

export async function putEndless(
	kind: string,
	score: EndlessEntryWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await apiRequest('PUT', `/me/learn/endless/${kind}`, {
		baseUrl,
		fetchFn,
		body: score,
		session: true
	});
}

/** `PATCH /me` with prefs only; the response (the `/me` body) isn't needed. */
export async function patchPrefs(
	prefs: LearnPrefsWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await apiRequest('PATCH', '/me', { baseUrl, fetchFn, body: { prefs }, session: true });
}

/** The merged progress; throws on any failure, so the caller keeps its local copy. */
export async function importLearn(
	body: LearnImportWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<LearnWire> {
	const response = await apiRequest('POST', '/me/learn/import', {
		baseUrl,
		fetchFn,
		body,
		session: true
	});
	return (await response.json()) as LearnWire;
}
