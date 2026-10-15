import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync } from 'svelte';
import { userEvent } from 'vitest/browser';
import { cleanupAll, render } from '$lib/table/test-render';
import Settings from './Settings.svelte';
import type { AutoArm, ClientPrefs } from './client-prefs';
import { DEFAULT_AUTO_ARM, DEFAULT_CLIENT_PREFS } from './settings-storage';

function mountSettings(autoArm: AutoArm, prefs: ClientPrefs) {
	const onAutoArmChange = vi.fn();
	const onPrefsChange = vi.fn();
	const onReset = vi.fn();
	render(Settings, { autoArm, prefs, onAutoArmChange, onPrefsChange, onReset });
	flushSync();
	return { onAutoArmChange, onPrefsChange, onReset };
}

function visiblePanel(): HTMLElement {
	return document.querySelector<HTMLElement>('[role="tabpanel"]:not([hidden])')!;
}

describe('Settings tabs', () => {
	afterEach(cleanupAll);

	it('switches panels on click and with arrow keys, wrapping at the ends', async () => {
		mountSettings(DEFAULT_AUTO_ARM, DEFAULT_CLIENT_PREFS);
		const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')];

		tabs[1].click();
		flushSync();
		expect(visiblePanel().id).toBe(tabs[1].getAttribute('aria-controls'));

		tabs[1].focus();
		await userEvent.keyboard('{ArrowRight}');
		expect(document.activeElement).toBe(tabs[2]);
		expect(tabs[2].getAttribute('aria-selected')).toBe('true');

		await userEvent.keyboard('{ArrowRight}');
		expect(document.activeElement).toBe(tabs[0]);
		expect(visiblePanel().id).toBe(tabs[0].getAttribute('aria-controls'));
	});
});

describe('Settings reset', () => {
	afterEach(cleanupAll);

	it('is disabled while everything is at its default', () => {
		mountSettings(DEFAULT_AUTO_ARM, DEFAULT_CLIENT_PREFS);
		const reset = document.querySelector<HTMLButtonElement>('[data-testid="settings-reset"]')!;
		expect(reset.disabled).toBe(true);
	});

	it('restores default prefs and auto-arm', () => {
		const { onAutoArmChange, onPrefsChange, onReset } = mountSettings(
			{ noCalls: true, autoPassChow: false },
			{ ...DEFAULT_CLIENT_PREFS, motion: 'reduced', discardMode: 'one-tap' }
		);
		const reset = document.querySelector<HTMLButtonElement>('[data-testid="settings-reset"]')!;
		expect(reset.disabled).toBe(false);
		reset.click();
		expect(onAutoArmChange).toHaveBeenCalledWith(DEFAULT_AUTO_ARM);
		expect(onPrefsChange).toHaveBeenCalledWith(DEFAULT_CLIENT_PREFS);
		expect(onReset).toHaveBeenCalledOnce();
	});
});
