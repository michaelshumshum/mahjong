import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import TimerRing from './TimerRing.svelte';

// The countdown itself is a CSS animation (docs/03-frontend.md §5: no JS ticker), so a unit
// test can't wait out real elapsed time to observe it "about to expire". Instead this asserts
// the CSS custom properties the component derives from `durationMs` — the same values that
// drive the `deplete`/`warn-pulse` keyframes' timing — are correct for given inputs.
// `computeRingTiming` (timer-ring.spec.ts) covers the underlying math in isolation; this file
// just checks the component wires that output into rendered markup correctly.
describe('TimerRing', () => {
	it('renders deplete/warn CSS custom properties for a duration longer than the warn window', () => {
		const { body } = render(TimerRing, { props: { durationMs: 5000 } });
		expect(body).toContain('--deplete-duration: 5000ms');
		expect(body).toContain('--warn-delay: 3500ms');
		expect(body).toContain('--warn-duration: 1500ms');
	});

	it('starts the "about to expire" state immediately for a duration under the warn window', () => {
		const { body } = render(TimerRing, { props: { durationMs: 800 } });
		expect(body).toContain('--warn-delay: 0ms');
		expect(body).toContain('--warn-duration: 800ms');
	});

	it('respects a custom warn window', () => {
		const { body } = render(TimerRing, { props: { durationMs: 3000, warnWindowMs: 500 } });
		expect(body).toContain('--warn-delay: 2500ms');
		expect(body).toContain('--warn-duration: 500ms');
	});

	it('labels remaining whole seconds for assistive tech', () => {
		const { body } = render(TimerRing, { props: { durationMs: 4200 } });
		expect(body).toContain('aria-label="5s remaining"');
	});

	it('sizes the ring from the size prop', () => {
		const { body } = render(TimerRing, { props: { durationMs: 1000, size: 96 } });
		expect(body).toContain('--ring-size: 96px');
	});
});
