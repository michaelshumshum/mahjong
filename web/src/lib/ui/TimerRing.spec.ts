import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import TimerRing from './TimerRing.svelte';

// CSS-animation countdown (no JS ticker): asserts custom properties derived from `durationMs`
// instead of waiting on real elapsed time. `computeRingTiming` (timer-ring.spec.ts) covers the math.
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
