import { describe, expect, it } from 'vitest';
import { createTable, fetchTables, seatedCount, type TableSummary } from './lobby';
import { DEFAULT_RULESET } from './ruleset';

const TABLE: TableSummary = {
	id: 'ABC123',
	status: 'open',
	hand_no: 1,
	seats: [
		{ status: 'connected', name: 'Alice' },
		{ status: 'empty', name: null },
		{ status: 'bot', name: 'FaanBot' },
		{ status: 'empty', name: null }
	]
};

function stubFetch(status: number, body: unknown, seen: string[] = []): typeof fetch {
	return (async (input: RequestInfo | URL) => {
		seen.push(String(input));
		return new Response(JSON.stringify(body), { status });
	}) as typeof fetch;
}

describe('fetchTables', () => {
	it('unwraps the tables list from the base url', async () => {
		const seen: string[] = [];
		const tables = await fetchTables('http://api.test', stubFetch(200, { tables: [TABLE] }, seen));
		expect(seen).toEqual(['http://api.test/tables']);
		expect(tables).toEqual([TABLE]);
	});

	it('throws on a non-2xx response', async () => {
		await expect(fetchTables('http://api.test', stubFetch(503, {}))).rejects.toThrow('503');
	});
});

describe('seatedCount', () => {
	it('counts every non-empty seat, bots included', () => {
		expect(seatedCount(TABLE)).toBe(2);
	});
});

describe('createTable', () => {
	function stubPost(
		status: number,
		body: unknown,
		seen: { url: string; init?: RequestInit }[] = []
	): typeof fetch {
		return (async (input: RequestInfo | URL, init?: RequestInit) => {
			seen.push({ url: String(input), init });
			return new Response(JSON.stringify(body), { status });
		}) as typeof fetch;
	}

	it('POSTs the request body as JSON and returns the parsed response', async () => {
		const seen: { url: string; init?: RequestInit }[] = [];
		const response = {
			table_id: 'ABC123',
			ruleset_preset: 'hk_casual',
			ruleset: { ...DEFAULT_RULESET, min_faan: 1 }
		};
		const result = await createTable(
			{ ruleset: 'hk_casual' },
			'http://api.test',
			stubPost(200, response, seen)
		);
		expect(seen).toEqual([
			{
				url: 'http://api.test/tables',
				init: {
					method: 'POST',
					headers: { 'Content-Type': 'application/json' },
					body: JSON.stringify({ ruleset: 'hk_casual' })
				}
			}
		]);
		expect(result).toEqual(response);
	});

	it('defaults to an empty body', async () => {
		const seen: { url: string; init?: RequestInit }[] = [];
		await createTable(
			undefined,
			'http://api.test',
			stubPost(
				200,
				{ table_id: 'ABC123', ruleset_preset: 'hk_classic', ruleset: DEFAULT_RULESET },
				seen
			)
		);
		expect(seen[0].init?.body).toBe('{}');
	});

	it('throws on a non-2xx response', async () => {
		await expect(createTable({}, 'http://api.test', stubPost(500, {}))).rejects.toThrow('500');
	});
});
