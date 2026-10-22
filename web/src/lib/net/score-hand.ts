import { apiBaseUrl } from './lobby';
import type { RuleSet } from './ruleset';

// hand-written like lobby.ts: POST /score is plain HTTP. server: app/api_models.py's
// ScoreHandRequest/ScoreHandResponse.
export interface ScoreHandRequest {
	ruleset: string;
	rules?: RuleSet;
	// 14 concealed tile codes; the last is the winning tile
	tiles: string[];
	flowers: string[];
	self_drawn: boolean;
	// 0 = East .. 3 = North
	seat_wind: number;
	prevailing_wind: number;
}

export interface ScoreHandResponse {
	winning: boolean;
	total_faan: number | null;
	breakdown: Record<string, number>;
	clears_min_faan: boolean | null;
	points: number | null;
	min_faan: number;
}

export async function scoreHand(
	body: ScoreHandRequest,
	baseUrl: string = apiBaseUrl(),
	fetchFn: typeof fetch = fetch
): Promise<ScoreHandResponse> {
	const response = await fetchFn(`${baseUrl}/score`, {
		method: 'POST',
		headers: { 'Content-Type': 'application/json' },
		body: JSON.stringify(body)
	});
	if (!response.ok) throw new Error(`POST /score failed: ${response.status}`);
	return (await response.json()) as ScoreHandResponse;
}
