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
// CreateTableDialog pulls in $lib/net/lobby, which reads $env/dynamic/public -- unset outside
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
		expect(target.querySelector('[data-testid="lobby-create-table"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-join-game-link"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-practice-bots"]')).not.toBeNull();
	});

	it('opens the create-table dialog when the create button is clicked', async () => {
		component = mount(LobbyPage, { target });
		const createButton = target.querySelector(
			'[data-testid="lobby-create-table"]'
		) as HTMLButtonElement;
		expect(createButton).not.toBeNull();
		createButton.click();
		await Promise.resolve();
		expect(target.querySelector('[role="dialog"]')).not.toBeNull();
	});

	it('navigates to /tables when the join link is clicked', () => {
		component = mount(LobbyPage, { target });
		const joinLink = target.querySelector(
			'[data-testid="lobby-join-game-link"]'
		) as HTMLAnchorElement;
		expect(joinLink?.getAttribute('href')).toBe('/tables');
	});
});
