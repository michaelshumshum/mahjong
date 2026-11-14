import { apiBaseUrl, apiRequest } from './lobby';
import type { RuleSet } from './ruleset';

// hand-written like lobby.ts: POST /score is plain HTTP. server: app/api_models.py's
// ScoreHandRequest/ScoreHandResponse.
export interface ScoreHandRequest {
	ruleset: string;
	rules?: RuleSet;
	// 14 tile codes; the last is the winning tile
	tiles: string[];
	flowers: string[];
	self_drawn: boolean;
	// false: one set was claimed from another player
	fully_concealed: boolean;
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
	const response = await apiRequest('POST', '/score', { baseUrl, fetchFn, body });
	return (await response.json()) as ScoreHandResponse;
}
