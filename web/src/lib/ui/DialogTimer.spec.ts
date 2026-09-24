import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import DialogTimer from './DialogTimer.svelte';

// Auto-close firing is covered in auto-close.spec.ts (svelte/server can't run $effect) --
// this file only covers that DialogTimer wires its props into the TimerRing markup.
describe('DialogTimer', () => {
	const noop = () => {};

	it('renders a timer ring sized from the size prop', () => {
		const { body } = render(DialogTimer, { props: { durationMs: 5000, onClose: noop, size: 40 } });
		expect(body).toContain('--ring-size: 40px');
		expect(body).toContain('--deplete-duration: 5000ms');
	});

	it('defaults to the standard ring size when none is given', () => {
		const { body } = render(DialogTimer, { props: { durationMs: 5000, onClose: noop } });
		expect(body).toContain('--ring-size: 56px');
	});
});
