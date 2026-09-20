import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import DialogTimer from './DialogTimer.svelte';

// The auto-close firing (the scheduled setTimeout calling onClose) is covered without real
// elapsed time in auto-close.spec.ts (vi.useFakeTimers around scheduleAutoDismiss) -- svelte/
// server can't run `$effect`, so this file only covers that DialogTimer wires its props into the
// TimerRing markup it wraps. Same split as Toast.spec.ts/auto-close.spec.ts.
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
