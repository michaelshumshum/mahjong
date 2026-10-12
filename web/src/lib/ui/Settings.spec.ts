import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Settings from './Settings.svelte';
import type { AutoArm, ClientPrefs } from './Settings.svelte';

// Toggle firing is covered end-to-end (routes/page.e2e.ts) -- this file covers that rendered
// checked/unchecked state matches the given props.
describe('Settings', () => {
	const noop = () => {};
	const offArm: AutoArm = { noCalls: false, autoPassChow: false };
	const offPrefs: ClientPrefs = {
		soundEnabled: false,
		motion: 'system',
		discardMode: 'two-step',
		haptics: false,
		announceAllDiscards: false,
		tileSize: 'medium',
		handOrder: 'auto'
	};

	it('renders both pre-arm toggles unchecked when both are off', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(0);
	});

	it('reflects a checked no_calls toggle', () => {
		const autoArm: AutoArm = { noCalls: true, autoPassChow: false };
		const { body } = render(Settings, {
			props: { autoArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		// exactly one checkbox checked: no_calls, not auto_pass_chow or sound
		expect([...body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(1);
	});

	it('reflects both pre-arm toggles and sound on together', () => {
		const autoArm: AutoArm = { noCalls: true, autoPassChow: true };
		const prefs: ClientPrefs = {
			soundEnabled: true,
			motion: 'system',
			discardMode: 'two-step',
			haptics: false,
			announceAllDiscards: false,
			tileSize: 'medium',
			handOrder: 'auto'
		};
		const { body } = render(Settings, {
			props: { autoArm, prefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(3);
	});

	it('marks the motion radio matching the current pref as checked, others not', () => {
		const prefs: ClientPrefs = {
			soundEnabled: false,
			motion: 'reduced',
			discardMode: 'two-step',
			haptics: false,
			announceAllDiscards: false,
			tileSize: 'medium',
			handOrder: 'auto'
		};
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect(body).toMatch(/value="reduced"[^>]*checked/);
		expect(body).not.toMatch(/value="system"[^>]*checked/);
		expect(body).not.toMatch(/value="full"[^>]*checked/);
	});

	it('has no auto_win toggle: declining a win is never a pre-arm', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		const labels = [...body.matchAll(/class="switch-label[^"]*">([^<]*)</g)].map((m) => m[1]);
		expect(labels.length).toBeGreaterThan(0);
		expect(labels.some((label) => label.toLowerCase().includes('win'))).toBe(false);
	});

	it('renders three tabs with only the first panel visible', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/role="tab"/g)]).toHaveLength(3);
		expect([...body.matchAll(/role="tabpanel"[^>]*hidden/g)]).toHaveLength(2);
		expect(body).toMatch(
			/role="tab"[^>]*aria-selected="true"[^>]*data-testid="settings-tab-calls"/
		);
	});

	it('describes the selected discard mode and the pre-arm toggles', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect(body).toContain('Tap a tile to lift it, tap it again to discard.');
		expect(body).not.toContain('Tap a tile to discard it straight away.');
		expect(body).toContain('Pass every pung, kong and chow offer automatically.');
	});

	it('renders the language switcher as its own section', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect(body).toContain('Language');
		expect([...body.matchAll(/type="radio"[^>]*name="locale"/g)]).toHaveLength(2);
	});

	it('reflects a checked haptics toggle independently of sound', () => {
		const prefs: ClientPrefs = {
			soundEnabled: false,
			motion: 'system',
			discardMode: 'two-step',
			haptics: true,
			announceAllDiscards: false,
			tileSize: 'medium',
			handOrder: 'auto'
		};
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(1);
	});

	it('marks the discard-mode radio matching the current pref as checked, others not', () => {
		const prefs: ClientPrefs = {
			soundEnabled: false,
			motion: 'system',
			discardMode: 'one-tap',
			haptics: false,
			announceAllDiscards: false,
			tileSize: 'medium',
			handOrder: 'auto'
		};
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/type="radio"[^>]*name="discardMode"/g)]).toHaveLength(2);
		expect(body).toMatch(/value="one-tap"[^>]*checked/);
		expect(body).not.toMatch(/value="two-step"[^>]*checked/);
	});

	it('marks the tile size segment matching the current pref', () => {
		const { body } = render(Settings, {
			props: {
				autoArm: offArm,
				prefs: { ...offPrefs, tileSize: 'large' },
				onAutoArmChange: noop,
				onPrefsChange: noop
			}
		});
		expect([...body.matchAll(/type="radio"[^>]*name="tileSize"/g)]).toHaveLength(3);
		expect(body).toMatch(/name="tileSize" value="large"[^>]*checked/);
		expect(body).not.toMatch(/name="tileSize" value="medium"[^>]*checked/);
	});

	it('offers an "Announce every discard" toggle, off by default', () => {
		const { body } = render(Settings, {
			props: { autoArm: offArm, prefs: offPrefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect(body).toContain('Announce every discard');
		const on = render(Settings, {
			props: {
				autoArm: offArm,
				prefs: { ...offPrefs, announceAllDiscards: true },
				onAutoArmChange: noop,
				onPrefsChange: noop
			}
		});
		expect([...on.body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(1);
	});
});
