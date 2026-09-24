import { env } from '$env/dynamic/public';
import type { RuleSet } from './ruleset';

// hand-written: GET/POST /tables are plain HTTP, outside the WS protocol make proto generates.
export interface SeatSummary {
	status: 'connected' | 'disconnected' | 'autoplay' | 'bot' | 'empty';
	name: string | null;
}

export interface TableSummary {
	id: string;
	status: 'open' | 'in_progress';
	hand_no: number;
	seats: SeatSummary[];
}

export function apiBaseUrl(): string {
	return env.PUBLIC_API_URL || 'http://localhost:8000';
}

// polls GET /healthz until it responds ok or timeoutMs elapses -- used by ApiConnectGate to gate
// the app on first load. 250ms interval matches the e2e suite's own backend-readiness poll.
export async function waitForApiHealthy(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch,
	timeoutMs = 10_000,
	onAttempt?: (attempt: number) => void
): Promise<boolean> {
	const deadline = Date.now() + timeoutMs;
	let attempt = 0;
	while (Date.now() < deadline) {
		attempt++;
		onAttempt?.(attempt);
		try {
			const response = await fetchFn(`${baseUrl}/healthz`);
			if (response.ok) return true;
		} catch {
			// not reachable yet -- keep polling until the deadline.
		}
		await new Promise((resolve) => setTimeout(resolve, 250));
	}
	return false;
}

export async function fetchTables(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<TableSummary[]> {
	const response = await fetchFn(`${baseUrl}/tables`);
	if (!response.ok) throw new Error(`GET /tables failed: ${response.status}`);
	const body = (await response.json()) as { tables: TableSummary[] };
	return body.tables;
}

export function seatedCount(table: TableSummary): number {
	return table.seats.filter((s) => s.status !== 'empty').length;
}

export interface CreateTableRequest {
	ruleset?: string;
	rules?: RuleSet;
	practice?: boolean;
}

export interface CreateTableResponse {
	table_id: string;
	ruleset_preset: string | null;
	ruleset: RuleSet;
}

// one-request table creation: resolves the ruleset and mints the table id together server-side.
export async function createTable(
	body: CreateTableRequest = {},
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<CreateTableResponse> {
	const response = await fetchFn(`${baseUrl}/tables`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) throw new Error(`POST /tables failed: ${response.status}`);
	return (await response.json()) as CreateTableResponse;
}
