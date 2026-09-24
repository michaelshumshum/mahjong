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
		const healthy = await waitForApiHealthy({
			baseUrl: 'http://api.test',
			fetchFn: stubFetch(200, {}, seen)
		});
		expect(healthy).toBe(true);
		expect(seen).toEqual(['http://api.test/healthz']);
	});

	it('retries with exponential backoff (1s, 2s, ...) until a later ping succeeds', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			if (calls < 3) return new Response('', { status: 503 });
			return new Response('', { status: 200 });
		}) as typeof fetch;

		const result = waitForApiHealthy({ baseUrl: 'http://api.test', fetchFn });
		await vi.advanceTimersByTimeAsync(1_000); // attempt 1 fails -> wait 1s before attempt 2
		await vi.advanceTimersByTimeAsync(2_000); // attempt 2 fails -> wait 2s before attempt 3

		expect(await result).toBe(true);
		expect(calls).toBe(3);
	});

	it('does not resolve before the doubled delay has fully elapsed', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			return new Response('', { status: 503 });
		}) as typeof fetch;

		waitForApiHealthy({ baseUrl: 'http://api.test', fetchFn, maxAttempts: 3, baseDelayMs: 1_000 });
		await vi.advanceTimersByTimeAsync(999);
		expect(calls).toBe(1); // still waiting out the 1s delay before attempt 2

		await vi.advanceTimersByTimeAsync(1_999); // crosses into the 1s mark but not the 2s one
		expect(calls).toBe(2); // still waiting out the 2s delay before attempt 3
	});

	it('gives up and returns false after maxAttempts, with no delay after the last attempt', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			return new Response('', { status: 503 });
		}) as typeof fetch;

		const result = waitForApiHealthy({
			baseUrl: 'http://api.test',
			fetchFn,
			maxAttempts: 4,
			baseDelayMs: 10
		});
		// backoff between the 4 attempts: 10ms, 20ms, 40ms (doubling from baseDelayMs)
		await vi.advanceTimersByTimeAsync(10);
		await vi.advanceTimersByTimeAsync(20);
		await vi.advanceTimersByTimeAsync(40);

		expect(await result).toBe(false);
		expect(calls).toBe(4);
	});

	it('defaults to a max of 5 attempts', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			return new Response('', { status: 503 });
		}) as typeof fetch;

		// 1s baseDelayMs default, doubling 4 times between 5 attempts: 1+2+4+8 = 15s
		const result = waitForApiHealthy({ baseUrl: 'http://api.test', fetchFn });
		await vi.advanceTimersByTimeAsync(15_000);

		expect(await result).toBe(false);
		expect(calls).toBe(5);
	});

	it('caps the backoff delay at maxDelayMs instead of doubling forever', async () => {
		vi.useFakeTimers();
		let calls = 0;
		const fetchFn = (async () => {
			calls++;
			return new Response('', { status: 503 });
		}) as typeof fetch;

		// uncapped doubling from 10_000 would be 10s, 20s, 40s, 80s; capped at 15s it's 10s, 15s,
		// 15s, 15s -- 55s total instead of 150s.
		const result = waitForApiHealthy({
			baseUrl: 'http://api.test',
			fetchFn,
			maxAttempts: 5,
			baseDelayMs: 10_000,
			maxDelayMs: 15_000
		});
		await vi.advanceTimersByTimeAsync(55_000);

		expect(await result).toBe(false);
		expect(calls).toBe(5);
	});

	it('reports each attempt number via onAttempt, 1-indexed', async () => {
		vi.useFakeTimers();
		const fetchFn = (async () => new Response('', { status: 503 })) as typeof fetch;
		const seen: number[] = [];

		const result = waitForApiHealthy({
			baseUrl: 'http://api.test',
			fetchFn,
			maxAttempts: 3,
			baseDelayMs: 10,
			onAttempt: (n) => seen.push(n)
		});
		await vi.advanceTimersByTimeAsync(10);
		await vi.advanceTimersByTimeAsync(20);
		await result;

		expect(seen).toEqual([1, 2, 3]);
	});

	it('reports the scheduled delay via onRetryScheduled before each wait', async () => {
		vi.useFakeTimers();
		const fetchFn = (async () => new Response('', { status: 503 })) as typeof fetch;
		const seen: number[] = [];

		const result = waitForApiHealthy({
			baseUrl: 'http://api.test',
			fetchFn,
			maxAttempts: 3,
			baseDelayMs: 10,
			onRetryScheduled: (delayMs) => seen.push(delayMs)
		});
		await vi.advanceTimersByTimeAsync(10);
		await vi.advanceTimersByTimeAsync(20);
		await result;

		// only fires between attempts (2 gaps for 3 attempts), never after the last one
		expect(seen).toEqual([10, 20]);
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
