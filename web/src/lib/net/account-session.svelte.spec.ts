import { describe, expect, it, vi } from 'vitest';
import { AccountSession } from './account-session.svelte';
import type { Me } from './account';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

const ME: Me = {
	id: '00000000-0000-0000-0000-000000000001',
	display_name: 'Ann',
	created_at: '2026-11-01T00:00:00Z',
	training_consent_at: null,
	consent_version: null
};

function respond(status: number, body?: unknown) {
	return vi.fn<typeof fetch>(async () =>
		body === undefined ? new Response(null, { status }) : Response.json(body, { status })
	);
}

describe('AccountSession.load', () => {
	it('sends no request and turns off when the flag is off', async () => {
		const fetchFn = respond(200, ME);
		const session = new AccountSession();
		await session.load({ enabled: false, fetchFn });
		expect(fetchFn).not.toHaveBeenCalled();
		expect(session.state).toEqual({ status: 'off' });
		expect(session.user).toBeNull();
	});

	it('signs in from a 200, sending the cookie', async () => {
		const fetchFn = respond(200, ME);
		const session = new AccountSession();
		await session.load({ enabled: true, baseUrl: 'http://api', fetchFn });
		expect(fetchFn).toHaveBeenCalledWith('http://api/me', { credentials: 'include' });
		expect(session.state).toEqual({ status: 'signedIn', user: ME });
		expect(session.user).toEqual(ME);
	});

	it.each([401, 404])('is a guest on %i', async (status) => {
		const session = new AccountSession();
		await session.load({ enabled: true, fetchFn: respond(status) });
		expect(session.state).toEqual({ status: 'guest' });
		expect(session.user).toBeNull();
	});

	it('is a guest when the api errors or is unreachable', async () => {
		const failing = new AccountSession();
		await failing.load({ enabled: true, fetchFn: respond(500) });
		expect(failing.state).toEqual({ status: 'guest' });

		const offline = new AccountSession();
		const fetchFn = vi.fn<typeof fetch>(async () => {
			throw new TypeError('network');
		});
		await offline.load({ enabled: true, fetchFn });
		expect(offline.state).toEqual({ status: 'guest' });
	});

	it('is loading until load runs', () => {
		expect(new AccountSession().state).toEqual({ status: 'loading' });
	});
});
