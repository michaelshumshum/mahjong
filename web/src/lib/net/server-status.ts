import { apiBaseUrl } from './lobby';

// hand-written like lobby.ts: GET /status is plain HTTP. server: app/api_models.py's StatusResponse.
export type ServerStatus = 'ok' | 'degraded' | 'draining';

export interface LoadPoint {
	ts: number;
	players: number;
	tables: number;
	bot_p95_ms: number | null;
	loop_lag_ms: number;
}

export interface StatusResponse {
	status: ServerStatus;
	uptime_seconds: number;
	players_online: number;
	spectators: number;
	tables_playing: number;
	tables_waiting: number;
	capacity_pct: number | null;
	games_finished_24h: number | null;
	bot_decision_ms: { p50_ms: number; p95_ms: number } | null;
	loop_lag_ms: number;
	history: LoadPoint[];
}

export async function fetchServerStatus(
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<StatusResponse> {
	const response = await fetchFn(`${baseUrl}/status`);
	if (!response.ok) throw new Error(`GET /status failed: ${response.status}`);
	return (await response.json()) as StatusResponse;
}
