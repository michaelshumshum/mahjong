import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import LobbyPage from '../../routes/+page.svelte';
import { accountSession } from '$lib/net/account-session.svelte';

// dynamic import inside the factory itself -- vi.mock factories run lazily, but a
// vi.hoisted()-style outer-scope reference here would throw (web/AGENTS.md's vi.mock note).
vi.mock('$lib/paraglide/messages.js', async () => {
	const { createMessagesProxy } = await import('../../test/mocks');
	return { m: createMessagesProxy() };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/') } }));
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

	function openMenu(): void {
		target.querySelector<HTMLButtonElement>('[data-testid="lobby-menu-button"]')!.click();
		flushSync();
	}

	it('renders the lobby actions', () => {
		component = mount(LobbyPage, { target });
		expect(target.querySelector('[data-testid="lobby-play-online"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-practice-bots"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="lobby-learn"]')).not.toBeNull();
		expect(target.querySelectorAll('.action-card')).toHaveLength(3);
	});

	it('links play online to the tables page', () => {
		component = mount(LobbyPage, { target });
		const playLink = target.querySelector('[data-testid="lobby-play-online"]') as HTMLAnchorElement;
		expect(playLink?.getAttribute('href')).toBe('/tables');
	});

	it('links the learn card to /learn', () => {
		component = mount(LobbyPage, { target });
		const learn = target.querySelector('[data-testid="lobby-learn"]')!;
		expect(learn.getAttribute('href')).toBe('/learn');
		expect(learn.textContent?.trim()).toBe('lobby_learnButton');
	});

	it('keeps the faan guide, settings and language in the menu, not on the page', () => {
		component = mount(LobbyPage, { target });
		for (const id of ['lobby-guide', 'lobby-settings', 'lobby-language']) {
			expect(target.querySelector(`[data-testid="${id}"]`)).toBeNull();
		}
		openMenu();
		const items = [...target.querySelectorAll('[data-testid="lobby-menu"] .item')];
		expect(items.map((item) => item.getAttribute('data-testid'))).toEqual([
			'lobby-menu-guest-name',
			'lobby-guide',
			'lobby-settings',
			'lobby-language'
		]);
		for (const item of items) expect(item.querySelector('svg')).not.toBeNull();
	});

	it('asks a nameless guest for a name once the account status is known', () => {
		accountSession.state = { status: 'off' };
		try {
			component = mount(LobbyPage, { target });
			flushSync();
			const input = target.querySelector<HTMLInputElement>('[data-testid="welcome-name"]')!;
			input.value = 'Mei';
			input.dispatchEvent(new Event('input', { bubbles: true }));
			flushSync();
			target.querySelector<HTMLButtonElement>('[data-testid="welcome-guest"]')!.click();
			flushSync();
			expect(target.querySelector('[data-testid="welcome-dialog"]')).toBeNull();
			expect(localStorage.getItem('mahjong:displayName:v1')).toBe(JSON.stringify('Mei'));
		} finally {
			accountSession.state = { status: 'loading' };
			localStorage.clear();
		}
	});

	it('does not ask a guest who already has a name', () => {
		localStorage.setItem('mahjong:displayName:v1', JSON.stringify('Mei'));
		accountSession.state = { status: 'off' };
		try {
			component = mount(LobbyPage, { target });
			flushSync();
			expect(target.querySelector('[data-testid="welcome-dialog"]')).toBeNull();
		} finally {
			accountSession.state = { status: 'loading' };
			localStorage.clear();
		}
	});

	it('opens the faan guide from the menu', async () => {
		component = mount(LobbyPage, { target });
		openMenu();
		const guide = target.querySelector<HTMLButtonElement>('[data-testid="lobby-guide"]')!;
		guide.click();
		await Promise.resolve();
		expect(target.querySelector('dialog')?.open).toBe(true);
	});

	it('links status, privacy, terms and the source code, in that order', () => {
		component = mount(LobbyPage, { target });
		const links = [...target.querySelectorAll('.corner-links a')];
		expect(links.map((link) => link.getAttribute('data-testid'))).toEqual([
			'lobby-status-link',
			'lobby-privacy-link',
			'lobby-terms-link',
			'lobby-source-link'
		]);
		expect(links.slice(0, 3).map((link) => link.getAttribute('href'))).toEqual([
			'/status',
			'/privacy',
			'/terms'
		]);
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

	it('opens Settings from the menu, with stored prefs', async () => {
		localStorage.setItem(
			'mahjong:clientPrefs:v1',
			JSON.stringify({ soundEnabled: true, motion: 'system', sfxVolume: 35 })
		);
		component = mount(LobbyPage, { target });
		openMenu();
		target.querySelector<HTMLButtonElement>('[data-testid="lobby-settings"]')!.click();
		await Promise.resolve();
		expect(target.querySelector('dialog')?.open).toBe(true);
		const volume = target.querySelector<HTMLInputElement>('[data-testid="settings-sfx-volume"]')!;
		expect(volume.valueAsNumber).toBe(35);
		localStorage.clear();
	});

	it('names the language item in the target language', () => {
		component = mount(LobbyPage, { target });
		openMenu();
		const label = target.querySelector('[data-testid="lobby-language"] .item-label')!;
		expect(label.textContent?.trim()).toBe('lobby_languageButton');
		expect(label.getAttribute('lang')).toBe('zh-Hant');
	});

	it('marks the play-online link for the button click sound', () => {
		component = mount(LobbyPage, { target });
		const play = target.querySelector('[data-testid="lobby-play-online"]')!;
		expect(play.getAttribute('data-sfx')).toBe('on');
	});
});
