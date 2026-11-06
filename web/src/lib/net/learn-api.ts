import type { Band } from '$lib/learn/generated/lessons';
import { apiBaseUrl } from './lobby';

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

const WITH_SESSION: RequestInit = { credentials: 'include' };

async function send(
	path: string,
	method: string,
	body: unknown,
	baseUrl: string,
	fetchFn: typeof fetch
): Promise<Response> {
	const response = await fetchFn(`${baseUrl}${path}`, {
		...WITH_SESSION,
		method,
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) throw new Error(`${method} ${path} failed: ${response.status}`);
	return response;
}

export async function fetchLearn(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<LearnWire> {
	const response = await fetchFn(`${baseUrl}/me/learn`, WITH_SESSION);
	if (!response.ok) throw new Error(`GET /me/learn failed: ${response.status}`);
	return (await response.json()) as LearnWire;
}

export async function putLesson(
	id: string,
	entry: LessonEntryWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await send(`/me/learn/${encodeURIComponent(id)}`, 'PUT', entry, baseUrl, fetchFn);
}

export async function putEndless(
	kind: string,
	score: EndlessEntryWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await send(`/me/learn/endless/${kind}`, 'PUT', score, baseUrl, fetchFn);
}

/** `PATCH /me` with prefs only; the response (the `/me` body) isn't needed. */
export async function patchPrefs(
	prefs: LearnPrefsWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	await send('/me', 'PATCH', { prefs }, baseUrl, fetchFn);
}

/** The merged progress; throws on any failure, so the caller keeps its local copy. */
export async function importLearn(
	body: LearnImportWire,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<LearnWire> {
	return (await (await send('/me/learn/import', 'POST', body, baseUrl, fetchFn)).json()) as LearnWire;
}
