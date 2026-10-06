import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import CenterHub from './CenterHub.svelte';

function props(overrides: Partial<Parameters<typeof CenterHub>[1]> = {}) {
	return {
		prevailing: 'E' as const,
		handNo: 3,
		dealer: 0 as const,
		turn: 0 as const,
		you: 0 as const,
		wallCount: 68,
		minFaan: 3,
		turnDurationMs: 15000,
		...overrides
	};
}

describe('CenterHub', () => {
	afterEach(cleanupAll);

	it('renders the hand number, wall count, and min-faan chip', () => {
		const { target } = render(CenterHub, props());
		expect(target.querySelector('.hub-hand')?.textContent).toContain('3');
		expect(target.querySelector('.wall-count strong')?.textContent).toContain('68');
		expect(target.querySelector('.hub-min-faan')?.textContent).toContain('3');
	});

	it('hides the min-faan chip when minFaan is null', () => {
		const { target } = render(CenterHub, props({ minFaan: null }));
		expect(target.querySelector('.hub-min-faan')).toBeNull();
	});

	it('renders one wind marker per seat, with the acting seat glowing', () => {
		const { target } = render(CenterHub, props({ turn: 2 }));
		const markers = target.querySelectorAll('.hub-marker');
		expect(markers).toHaveLength(4);
		expect(target.querySelectorAll('.hub-marker--turn')).toHaveLength(1);
	});

	it('shows the turn ring only when a duration is known', () => {
		const { target } = render(CenterHub, props({ turn: 0, turnDurationMs: 15000 }));
		expect(target.querySelector('.hub-marker-ring')).not.toBeNull();
	});

	it('shows no ring when the acting seat is not this client', () => {
		const { target } = render(CenterHub, props({ turn: 1, turnDurationMs: null }));
		expect(target.querySelector('.hub-marker-ring')).toBeNull();
	});
});
