import { describe, expect, it } from 'vitest';
import { fetchTables, seatedCount, type TableSummary } from './lobby';

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
