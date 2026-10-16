import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import LobbyPage from '../../routes/+page.svelte';

// dynamic import inside the factory itself -- vi.mock factories run lazily, but a
// vi.hoisted()-style outer-scope reference here would throw (web/AGENTS.md's vi.mock note).
vi.mock('$lib/paraglide/messages.js', async () => {
	const { createMessagesProxy } = await import('../../test/mocks');
	return { m: createMessagesProxy() };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
// PracticeSetupDialog pulls in $lib/net/lobby, which reads $env/dynamic/public -- unset outside
// SvelteKit's own dev/build server (web/AGENTS.md's $env note). Unused by anything under test.
vi.mock('$env/dynamic/public', () => ({ env: {} }));

describe('LobbyPage', () => {
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

	it('renders the lobby actions', () => {
		component = mount(LobbyPage, { target });
		expect(target.querySelector('[data-testid="lobby-play-online"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-practice-bots"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-guide"]')).not.toBeNull();
	});

	it('links play online to the tables page', () => {
		component = mount(LobbyPage, { target });
		const playLink = target.querySelector('[data-testid="lobby-play-online"]') as HTMLAnchorElement;
		expect(playLink?.getAttribute('href')).toBe('/tables');
	});

	it('opens the practice dialog when the practice button is clicked', async () => {
		component = mount(LobbyPage, { target });
		const practiceButton = target.querySelector(
			'[data-testid="lobby-practice-bots"]'
		) as HTMLButtonElement;
		practiceButton.click();
		await Promise.resolve();
		expect(target.querySelector('dialog')?.open).toBe(true);
	});
});
