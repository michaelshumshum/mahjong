import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Settings from './Settings.svelte';
import type { AutoArm, ClientPrefs } from './Settings.svelte';

// `onAutoArmChange`/`onPrefsChange` firing on toggle is exercised end-to-end
// (routes/page.e2e.ts), same as ClaimButtons' `onChoose` — svelte/server only renders markup,
// there's no DOM to dispatch a real change event against here. This file covers that the
// rendered checked/unchecked state matches the given props.
describe('Settings', () => {
	const noop = () => {};
	const offArm: AutoArm = { noCalls: false, autoPassChow: false };
	const offPrefs: ClientPrefs = { soundEnabled: false, motion: 'system' };

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
		const prefs: ClientPrefs = { soundEnabled: true, motion: 'system' };
		const { body } = render(Settings, {
			props: { autoArm, prefs, onAutoArmChange: noop, onPrefsChange: noop }
		});
		expect([...body.matchAll(/type="checkbox"[^>]*checked/g)]).toHaveLength(3);
	});

	it('marks the motion radio matching the current pref as checked, others not', () => {
		const prefs: ClientPrefs = { soundEnabled: false, motion: 'reduced' };
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
		expect(body.toLowerCase()).not.toContain('win');
	});
});
