import { env } from '$env/dynamic/public';
import { apiBaseUrl } from './lobby';

// hand-written like lobby.ts: /me and /auth/* are plain HTTP (docs/protocol.md §10 "Accounts").
// server: app/api_models.py's MeResponse.
export interface Me {
	id: string;
	display_name: string;
	created_at: string;
	training_consent_at: string | null;
	consent_version: string | null;
}

// same truthy set as the server's ACCOUNTS_ENABLED (app/accounts/config.py)
const TRUTHY = new Set(['1', 'true', 'yes', 'on']);

export function accountsEnabled(): boolean {
	return TRUTHY.has((env.PUBLIC_ACCOUNTS_ENABLED ?? '').trim().toLowerCase());
}

// the session cookie is host-only on the API host, so every /me and /auth call must include it
const WITH_SESSION: RequestInit = { credentials: 'include' };

/** The signed-in account, or null for a guest (401) or accounts off on the server (404). */
export async function fetchMe(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<Me | null> {
	const response = await fetchFn(`${baseUrl}/me`, WITH_SESSION);
	if (response.status === 401 || response.status === 404) return null;
	if (!response.ok) throw new Error(`GET /me failed: ${response.status}`);
	return (await response.json()) as Me;
}

// server: app/api_models.py's MePatch
export interface MePatch {
	display_name?: string;
	training_consent?: boolean;
}

export async function patchMe(
	body: MePatch,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<Me> {
	const response = await fetchFn(`${baseUrl}/me`, {
		...WITH_SESSION,
		method: 'PATCH',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) throw new Error(`PATCH /me failed: ${response.status}`);
	return (await response.json()) as Me;
}

/** Immediate and final; the caller asks for a typed confirmation first. */
export async function deleteMe(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	const response = await fetchFn(`${baseUrl}/me`, { ...WITH_SESSION, method: 'DELETE' });
	if (!response.ok) throw new Error(`DELETE /me failed: ${response.status}`);
}

/** `GET /me/export`'s JSON as a file body, untouched (server: ExportResponse). */
export async function exportMe(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<Blob> {
	const response = await fetchFn(`${baseUrl}/me/export`, WITH_SESSION);
	if (!response.ok) throw new Error(`GET /me/export failed: ${response.status}`);
	return response.blob();
}

// the server's Content-Disposition name; a cross-origin download can't read that header
export const EXPORT_FILENAME = 'mahjong-account.json';

export async function signOut(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<void> {
	const response = await fetchFn(`${baseUrl}/auth/logout`, { ...WITH_SESSION, method: 'POST' });
	if (!response.ok) throw new Error(`POST /auth/logout failed: ${response.status}`);
}

/** Full-page navigation target: Google's consent screen, then back to `next` on the web. */
export function signInUrl(next: string, baseUrl: string = apiBaseUrl()): string {
	return `${baseUrl}/auth/google/login?${new URLSearchParams({ next })}`;
}

export type SigninFlag = 'signup' | 'failed' | 'disabled';

// the query flags /auth/google/callback appends to `next` (docs/protocol.md §10 "Accounts")
const FLAG_PARAMS = ['signup', 'signin'] as const;

/** The callback's flag on `url`, and `url` without any of them. */
export function readSigninFlag(url: URL): { flag: SigninFlag | null; cleaned: URL } {
	const signin = url.searchParams.get('signin');
	const flag =
		url.searchParams.get('signup') === '1'
			? 'signup'
			: signin === 'failed' || signin === 'disabled'
				? signin
				: null;
	const cleaned = new URL(url);
	for (const param of FLAG_PARAMS) cleaned.searchParams.delete(param);
	return { flag, cleaned };
}
