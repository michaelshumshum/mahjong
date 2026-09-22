import { env } from '$env/dynamic/public';

// hand-written: `GET /tables` is plain HTTP, outside the WS protocol `make proto` generates
// (server/app/main.py's `TableList`).
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
