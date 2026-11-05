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
