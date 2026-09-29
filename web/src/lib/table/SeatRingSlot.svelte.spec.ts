import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatRingSlot from './SeatRingSlot.svelte';

describe('SeatRingSlot', () => {
	afterEach(cleanupAll);

	it('renders the wind label', () => {
		const { target } = render(SeatRingSlot, { label: '東', self: false });
		expect(target.textContent).toContain('東');
		expect(target.querySelector('.seat-ring-slot')).not.toBeNull();
	});

	it('marks the self seat with a solid accent style', () => {
		const { target } = render(SeatRingSlot, { label: '南', self: true });
		expect(target.querySelector('.seat-ring-slot--self')).not.toBeNull();
	});

	it('does not apply the self style to other seats', () => {
		const { target } = render(SeatRingSlot, { label: '西', self: false });
		expect(target.querySelector('.seat-ring-slot--self')).toBeNull();
	});
});
