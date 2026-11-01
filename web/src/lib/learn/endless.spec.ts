import { describe, expect, it, vi } from 'vitest';
import lesson from './generated/basics-isolated-honour.json';
import {
	EMPTY_SCORE,
	ENDLESS_RECENT,
	endlessUrl,
	fetchRandomLesson,
	recordEndlessAnswer,
	recordEndlessSkip,
	rememberRecent,
	type EndlessRequest
} from './endless';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

const BASE = 'http://api.test';
const REQUEST: EndlessRequest = { kind: 'best_discard', band: 'advanced', exclude: ['a', 'b'] };

function stubFetch(response: () => Response, seen: string[] = []): typeof fetch {
	return (async (input: RequestInfo | URL) => {
		seen.push(String(input));
		return response();
	}) as typeof fetch;
}

describe('fetchRandomLesson', () => {
	it('asks for the kind and band, excluding recent ids, and returns the lesson', async () => {
		const seen: string[] = [];
		const fetchFn = stubFetch(() => Response.json(lesson), seen);
		const fetched = await fetchRandomLesson(REQUEST, BASE, fetchFn);
		expect(fetched).toEqual({ ok: true, lesson });
		const url = new URL(seen[0]);
		expect(url.pathname).toBe('/lessons/random');
		expect(url.searchParams.get('kind')).toBe('best_discard');
		expect(url.searchParams.get('band')).toBe('advanced');
		expect(url.searchParams.getAll('exclude')).toEqual(['a', 'b']);
	});

	it('reads Retry-After on a 429', async () => {
		const limited = () => new Response('{}', { status: 429, headers: { 'Retry-After': '12' } });
		expect(await fetchRandomLesson(REQUEST, BASE, stubFetch(limited))).toEqual({
			ok: false,
			error: 'rate_limited',
			retryAfterS: 12
		});
		const bare = () => new Response('{}', { status: 429 });
		expect(await fetchRandomLesson(REQUEST, BASE, stubFetch(bare))).toEqual({
			ok: false,
			error: 'rate_limited',
			retryAfterS: null
		});
	});

	it('is unavailable on a server error, a network error or a puzzle of another kind', async () => {
		const unavailable = { ok: false, error: 'unavailable' };
		const down = () => new Response('', { status: 503 });
		expect(await fetchRandomLesson(REQUEST, BASE, stubFetch(down))).toEqual(unavailable);
		const offline = (async () => {
			throw new TypeError('Failed to fetch');
		}) as typeof fetch;
		expect(await fetchRandomLesson(REQUEST, BASE, offline)).toEqual(unavailable);
		const other = { ...REQUEST, kind: 'count_faan' as const };
		const fetchFn = stubFetch(() => Response.json(lesson));
		expect(await fetchRandomLesson(other, BASE, fetchFn)).toEqual(unavailable);
	});

	it('builds the url without excludes', () => {
		expect(endlessUrl({ ...REQUEST, exclude: [] }, BASE)).toBe(
			`${BASE}/lessons/random?kind=best_discard&band=advanced`
		);
	});
});

describe('rememberRecent', () => {
	it('keeps the newest ids once each, up to the cap', () => {
		expect(rememberRecent(['a', 'b'], 'a')).toEqual(['b', 'a']);
		let recent: string[] = [];
		for (let i = 0; i < ENDLESS_RECENT + 5; i++) recent = rememberRecent(recent, `id-${i}`);
		expect(recent).toHaveLength(ENDLESS_RECENT);
		expect(recent.at(-1)).toBe(`id-${ENDLESS_RECENT + 4}`);
		expect(recent[0]).toBe('id-5');
	});
});

describe('endless score', () => {
	it('counts first-try solves in a row and keeps the best', () => {
		let score = EMPTY_SCORE;
		score = recordEndlessAnswer(score, 'correct', false);
		score = recordEndlessAnswer(score, 'correct', false);
		expect(score).toEqual({ streak: 2, best: 2, solved: 2 });
	});

	it('a miss, partial included, ends the streak; the later solve counts as solved only', () => {
		const start = { streak: 3, best: 5, solved: 9 };
		const missed = recordEndlessAnswer(start, 'partial', false);
		expect(missed).toEqual({ streak: 0, best: 5, solved: 9 });
		expect(recordEndlessAnswer(missed, 'correct', true)).toEqual({
			streak: 0,
			best: 5,
			solved: 10
		});
		expect(recordEndlessAnswer(start, 'wrong', false).streak).toBe(0);
	});

	it('a skip ends the streak and keeps the rest', () => {
		expect(recordEndlessSkip({ streak: 4, best: 6, solved: 7 })).toEqual({
			streak: 0,
			best: 6,
			solved: 7
		});
	});
});
