import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProfilePage from '../../routes/profile/+page.svelte';
import { accountSession } from '$lib/net/account-session.svelte';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

describe('ProfilePage', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount>;

	beforeEach(() => {
		target = document.createElement('div');
		document.body.appendChild(target);
	});

	afterEach(() => {
		unmount(component);
		target.remove();
		accountSession.state = { status: 'loading' };
	});

	it('renders a back link to the lobby and a heading', () => {
		component = mount(ProfilePage, { target });
		const link = target.querySelector('a[href="/"]');
		expect(link).not.toBeNull();
		expect(link?.textContent).toContain('Lobby');
		expect(target.querySelector('h1')?.textContent).toBe('Profile');
		expect(target.querySelector('[data-testid="account-panel"]')).toBeNull();
	});

	it('shows the account panel once signed in', () => {
		accountSession.setUser({
			id: 'u',
			display_name: 'Ann',
			created_at: '2026-11-01T00:00:00Z',
			training_consent_at: null,
			consent_version: null
		});
		component = mount(ProfilePage, { target });
		flushSync();
		expect(target.querySelector('[data-testid="account-panel"]')?.textContent).toContain('Ann');
	});
});
