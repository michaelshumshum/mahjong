import { describe, expect, it, vi } from 'vitest';
import { deleteMe, exportMe, patchMe, readSigninFlag, signInUrl, signOut } from './account';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

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

	it('exportMe returns the body untouched', async () => {
		const body = '{"user":{"id":"u"},"identities":[],"games":[]}';
		const fetchFn = vi.fn<typeof fetch>(async () => new Response(body));
		const blob = await exportMe('http://api', fetchFn);
		expect(await blob.text()).toBe(body);
		expect(fetchFn).toHaveBeenCalledWith('http://api/me/export', { credentials: 'include' });
	});

	it('signOut posts with the cookie', async () => {
		const fetchFn = vi.fn<typeof fetch>(async () => new Response(null, { status: 204 }));
		await signOut('http://api', fetchFn);
		expect(fetchFn).toHaveBeenCalledWith('http://api/auth/logout', {
			credentials: 'include',
			method: 'POST'
		});
	});
});
