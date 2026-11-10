import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { userEvent } from 'vitest/browser';
import { cleanupAll, render } from '$lib/table/test-render';
import { accountSession } from '$lib/net/account-session.svelte';
import LobbyMenu from './LobbyMenu.svelte';

vi.mock('$env/dynamic/public', () => ({ env: {} }));
vi.mock('$app/state', () => ({ page: { url: new URL('http://localhost/') } }));

const ANN = {
	id: 'u',
	display_name: 'ann',
	created_at: '2026-11-01T00:00:00Z',
	training_consent_at: null,
	consent_version: null
};

function mountMenu(guestName: string | null = null) {
	const onOpenGuide = vi.fn();
	const onOpenSettings = vi.fn();
	const onEditGuestName = vi.fn();
	const onOpenAccount = vi.fn();
	const onOpenGames = vi.fn();
	const { target } = render(LobbyMenu, {
		guestName,
		onOpenGuide,
		onOpenSettings,
		onEditGuestName,
		onOpenAccount,
		onOpenGames
	});
	flushSync();
	const trigger = target.querySelector<HTMLButtonElement>('[data-testid="lobby-menu-button"]')!;
	const panel = () => target.querySelector<HTMLElement>('[data-testid="lobby-menu"]');
	const open = () => {
		trigger.click();
		flushSync();
	};
	return {
		target,
		trigger,
		panel,
		open,
		onOpenGuide,
		onOpenSettings,
		onEditGuestName,
		onOpenAccount,
		onOpenGames
	};
}

describe('LobbyMenu', () => {
	afterEach(() => {
		cleanupAll();
		accountSession.state = { status: 'loading' };
	});

	it('toggles a panel from the burger button', () => {
		const { trigger, panel, open } = mountMenu();
		expect(trigger.getAttribute('aria-expanded')).toBe('false');
		expect(panel()).toBeNull();
		open();
		expect(trigger.getAttribute('aria-expanded')).toBe('true');
		expect(trigger.getAttribute('aria-controls')).toBe(panel()!.id);
		open();
		expect(panel()).toBeNull();
	});

	it('shows no account section while accounts are off or loading', () => {
		accountSession.state = { status: 'off' };
		const { panel, open } = mountMenu();
		open();
		expect(panel()!.querySelector('[data-testid="account-panel"]')).toBeNull();
		expect(panel()!.querySelector('[data-testid="lobby-menu-sign-out"]')).toBeNull();
		expect(panel()!.querySelector('[data-testid="lobby-settings"]')).not.toBeNull();
	});

	it('offers a guest google sign-in and their guest name to edit', () => {
		accountSession.setUser(null);
		const { panel, open, onEditGuestName } = mountMenu('Mei');
		open();
		expect(panel()!.querySelector('[data-testid="google-sign-in"]')).not.toBeNull();
		expect(panel()!.querySelector('[data-testid="lobby-menu-account"]')).toBeNull();
		const rename = panel()!.querySelector<HTMLButtonElement>(
			'[data-testid="lobby-menu-guest-name"]'
		)!;
		expect(rename.querySelector('.item-value')?.textContent).toBe('Mei');
		rename.click();
		flushSync();
		expect(onEditGuestName).toHaveBeenCalledOnce();
		expect(panel()).toBeNull();
	});

	it('shows a signed-in player their initial, name, account and games, and sign out', () => {
		accountSession.setUser(ANN);
		const { trigger, panel, open, onOpenAccount, onOpenGames } = mountMenu();
		expect(trigger.querySelector('.avatar')?.textContent).toBe('A');
		open();
		expect(panel()!.querySelector('[data-testid="lobby-menu-name"]')?.textContent).toBe('ann');
		expect(panel()!.querySelector('[data-testid="lobby-menu-sign-out"]')).not.toBeNull();
		expect(panel()!.querySelector('[data-testid="lobby-menu-guest-name"]')).toBeNull();

		panel()!.querySelector<HTMLButtonElement>('[data-testid="lobby-menu-account"]')!.click();
		flushSync();
		expect(onOpenAccount).toHaveBeenCalledOnce();
		expect(panel()).toBeNull();
		open();
		panel()!.querySelector<HTMLButtonElement>('[data-testid="lobby-menu-games"]')!.click();
		flushSync();
		expect(onOpenGames).toHaveBeenCalledOnce();
	});

	it('closes and hands off when an item opens a dialog', () => {
		const { trigger, panel, open, onOpenSettings, onOpenGuide } = mountMenu();
		open();
		panel()!.querySelector<HTMLButtonElement>('[data-testid="lobby-settings"]')!.click();
		flushSync();
		expect(onOpenSettings).toHaveBeenCalledOnce();
		expect(panel()).toBeNull();
		expect(document.activeElement).toBe(trigger);

		open();
		panel()!.querySelector<HTMLButtonElement>('[data-testid="lobby-guide"]')!.click();
		flushSync();
		expect(onOpenGuide).toHaveBeenCalledOnce();
	});

	it('closes on Escape, refocusing the trigger, and on a click outside', async () => {
		const { trigger, panel, open } = mountMenu();
		open();
		await userEvent.keyboard('{Escape}');
		flushSync();
		expect(panel()).toBeNull();
		expect(document.activeElement).toBe(trigger);

		open();
		document.body.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
		flushSync();
		expect(panel()).toBeNull();
	});
});
