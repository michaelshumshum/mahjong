import { describe, expect, it, vi } from 'vitest';
import {
	deleteMe,
	fetchMyGames,
	joinName,
	patchMe,
	readSigninFlag,
	signInUrl,
	signOut,
	signupName
} from './account';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

describe('joinName', () => {
	it.each([
		// signed in: the account's name, so a session that expired before the handshake still
		// seats a guest under it, not "Guest N"
		['Ann', 'Typed', 'Ann'],
		['Ann', '', 'Ann'],
		[null, '  Bea ', 'Bea'],
		[null, '   ', undefined],
		[null, '', undefined]
	])('account %j, typed %j -> %j', (account, typed, expected) => {
		expect(joinName(account, typed)).toBe(expected);
	});
});

describe('signupName', () => {
	it.each([
		['Player 0427', 'Bea', 'Bea'],
		['Player 0427', '  Bea  ', 'Bea'],
		['Player 0427', '   ', 'Player 0427'],
		['Player 0427', null, 'Player 0427'],
		['Player 0427', 'x'.repeat(40), 'x'.repeat(24)]
	])('placeholder %s, guest name %j -> %s', (placeholder, guest, expected) => {
		expect(signupName(placeholder, guest)).toBe(expected);
	});
});

describe('readSigninFlag', () => {
	it.each([
		['/?signup=1', 'signup', '/'],
		['/learn?signin=failed', 'failed', '/learn'],
		['/table/ABC?signin=disabled&x=1', 'disabled', '/table/ABC?x=1'],
		['/?signin=bogus', null, '/'],
		['/tables?x=1', null, '/tables?x=1']
	])('%s -> %s, cleaned to %s', (path, flag, cleaned) => {
		const result = readSigninFlag(new URL(path, 'http://web'));
		expect(result.flag).toBe(flag);
		expect(result.cleaned.pathname + result.cleaned.search).toBe(cleaned);
	});
});

describe('account calls', () => {
	it('signInUrl carries the return path', () => {
		expect(signInUrl('/table/ABC?x=1', 'http://api')).toBe(
			'http://api/auth/google/login?next=%2Ftable%2FABC%3Fx%3D1'
		);
	});

	it('patchMe sends the cookie and returns the account', async () => {
		const me = { id: 'u', display_name: 'Ann' };
		const fetchFn = vi.fn<typeof fetch>(async () => Response.json(me));
		await expect(patchMe({ display_name: 'Ann' }, 'http://api', fetchFn)).resolves.toEqual(me);
		expect(fetchFn).toHaveBeenCalledWith('http://api/me', {
			credentials: 'include',
			method: 'PATCH',
			headers: { 'Content-Type': 'application/json' },
			body: '{"display_name":"Ann"}'
		});
	});

	it('patchMe throws on a 422', async () => {
		const fetchFn = vi.fn<typeof fetch>(async () => new Response(null, { status: 422 }));
		await expect(patchMe({ display_name: ' ' }, 'http://api', fetchFn)).rejects.toThrow('422');
	});

	it('deleteMe sends DELETE with the cookie and throws on a 401', async () => {
		const ok = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
		await deleteMe('http://api', ok);
		expect(ok).toHaveBeenCalledWith('http://api/me', { credentials: 'include', method: 'DELETE' });
		const gone = vi.fn<typeof fetch>(async () => new Response(null, { status: 401 }));
		await expect(deleteMe('http://api', gone)).rejects.toThrow('401');
	});

	it('signOut posts with the cookie', async () => {
		const fetchFn = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
		await signOut('http://api', fetchFn);
		expect(fetchFn).toHaveBeenCalledWith('http://api/auth/logout', {
			credentials: 'include',
			method: 'POST'
		});
	});

	it('fetchMyGames sends the cookie and only the cursor and filter given', async () => {
		const page = { games: [], next: null };
		const fetchFn = vi.fn<typeof fetch>(async () => Response.json(page));
		await expect(fetchMyGames({}, 'http://api', fetchFn)).resolves.toEqual(page);
		await fetchMyGames({ before: 12, mode: 'practice' }, 'http://api', fetchFn);
		expect(fetchFn.mock.calls).toEqual([
			['http://api/me/games', { credentials: 'include' }],
			['http://api/me/games?before=12&mode=practice', { credentials: 'include' }]
		]);
	});

	it('fetchMyGames throws on a 401', async () => {
		const fetchFn = vi.fn<typeof fetch>(async () => new Response(null, { status: 401 }));
		await expect(fetchMyGames({}, 'http://api', fetchFn)).rejects.toThrow('401');
	});
});
