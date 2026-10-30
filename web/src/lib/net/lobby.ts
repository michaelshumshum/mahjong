import { env } from '$env/dynamic/public';
import type { BotTier, WireSeatStatus } from './protocol';
import type { RuleSet } from './ruleset';
import { PRACTICE_DIFFICULTY_TO_TIER } from './practice-difficulty';
import type { PracticeSetup } from '$lib/ui/settings-storage';

// hand-written: GET/POST /tables are plain HTTP, outside the WS protocol make proto generates.
export interface SeatSummary {
	status: WireSeatStatus;
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

export interface WaitForApiHealthyOptions {
	baseUrl?: string;
	fetchFn?: typeof fetch;
	maxAttempts?: number;
	baseDelayMs?: number;
	maxDelayMs?: number;
	onAttempt?: (attempt: number) => void;
	// fires once a poll fails and a retry has been scheduled, with the delay before it -- lets a
	// caller show "next attempt in Ns" without duplicating the backoff math.
	onRetryScheduled?: (delayMs: number) => void;
}

// polls GET /healthz until ok or maxAttempts is exhausted (ApiConnectGate's load gate).
// exponential backoff between attempts, capped at maxDelayMs; no delay before the first attempt.
export async function waitForApiHealthy({
	baseUrl = apiBaseUrl(),
	fetchFn = fetch,
	maxAttempts = 5,
	baseDelayMs = 1_000,
	maxDelayMs = 30_000,
	onAttempt,
	onRetryScheduled
}: WaitForApiHealthyOptions = {}): Promise<boolean> {
	for (let attempt = 1; attempt <= maxAttempts; attempt++) {
		onAttempt?.(attempt);
		try {
			const response = await fetchFn(`${baseUrl}/healthz`);
			if (response.ok) return true;
		} catch {
			// not reachable yet -- keep retrying with backoff.
		}
		if (attempt < maxAttempts) {
			const delayMs = Math.min(baseDelayMs * 2 ** (attempt - 1), maxDelayMs);
			onRetryScheduled?.(delayMs);
			await new Promise((resolve) => setTimeout(resolve, delayMs));
		}
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
	// practice mode's per-seat difficulty picker: seat 1..3 -> a bot tier (seat 0 is the human
	// seat, never included). Server-side: app/api_models.py's CreateTableRequest.bot_tiers.
	bot_tiers?: Record<number, BotTier>;
	// left out of GET /tables; joinable by link or code only
	private?: boolean;
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

/** A practice table: seats 1-3 bound to bots at each seat's difficulty. */
export function practiceTableRequest(setup: PracticeSetup): CreateTableRequest {
	return {
		practice: true,
		bot_tiers: {
			1: PRACTICE_DIFFICULTY_TO_TIER[setup[1]],
			2: PRACTICE_DIFFICULTY_TO_TIER[setup[2]],
			3: PRACTICE_DIFFICULTY_TO_TIER[setup[3]]
		}
	};
}

export function createPracticeTable(
	setup: PracticeSetup,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<CreateTableResponse> {
	return createTable(practiceTableRequest(setup), baseUrl, fetchFn);
}
