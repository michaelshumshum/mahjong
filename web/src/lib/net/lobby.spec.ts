import { afterEach, describe, expect, it, vi } from 'vitest';
import {
	createTable,
	fetchTables,
	seatedCount,
	waitForApiHealthy,
	type TableSummary
} from './lobby';
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

describe('waitForApiHealthy', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('returns true as soon as /healthz responds ok', async () => {
		const seen: string[] = [];
		const healthy = await waitForApiHealthy('http://api.test', stubFetch(200, {}, seen));
		expect(healthy).toBe(true);
		expect(seen).toEqual(['http://api.test/healthz']);
	});

	it('keeps polling every 250ms until a later ping succeeds', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			if (calls < 3) return new Response('', { status: 503 });
			return new Response('', { status: 200 });
		}) as typeof fetch;

		const result = waitForApiHealthy('http://api.test', fetchFn);
		await vi.advanceTimersByTimeAsync(250);
		await vi.advanceTimersByTimeAsync(250);

		expect(await result).toBe(true);
		expect(calls).toBe(3);
	});

	it('gives up and returns false once the timeout elapses', async () => {
		vi.useFakeTimers();
		const fetchFn = (async () => new Response('', { status: 503 })) as typeof fetch;

		const result = waitForApiHealthy('http://api.test', fetchFn, 600);
		// the deadline is only rechecked at the top of the loop, after each 250ms wait -- advance
		// past the next poll boundary (750ms) so the final over-deadline check actually runs.
		await vi.advanceTimersByTimeAsync(1000);

		expect(await result).toBe(false);
	});

	it('reports each attempt number via onAttempt, 1-indexed', async () => {
		vi.useFakeTimers();
		const fetchFn = (async () => new Response('', { status: 503 })) as typeof fetch;
		const seen: number[] = [];

		const result = waitForApiHealthy('http://api.test', fetchFn, 600, (n) => seen.push(n));
		await vi.advanceTimersByTimeAsync(1000);
		await result;

		expect(seen).toEqual([1, 2, 3]);
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
