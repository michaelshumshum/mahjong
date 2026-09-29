import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { mount, unmount } from 'svelte';
import ProfilePage from '../../routes/profile/+page.svelte';

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
	});

	it('renders a back link to the lobby and a heading', () => {
		component = mount(ProfilePage, { target });
		const link = target.querySelector('a[href="/"]');
		expect(link).not.toBeNull();
		expect(link?.textContent).toContain('Lobby');
		expect(target.querySelector('h1')?.textContent).toBe('Profile');
	});
});
