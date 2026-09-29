import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatRing from './SeatRing.svelte';

describe('SeatRing', () => {
	afterEach(cleanupAll);

	it('renders four occupancy slots in the expected positions', () => {
		const { target } = render(SeatRing, {
			you: 0,
			dealer: 0,
			seatStatus: ['connected', 'empty', 'connected', 'empty'],
			names: ['You', null, 'Carol', null]
		});
		expect(target.querySelectorAll('.seat-ring-pos')).toHaveLength(4);
		expect(target.querySelectorAll('.seat-ring-pos--across .seat-ring-slot')).toHaveLength(1);
		expect(target.querySelectorAll('.seat-ring-pos--left .seat-ring-slot')).toHaveLength(1);
		expect(target.querySelectorAll('.seat-ring-pos--right .seat-ring-slot')).toHaveLength(1);
		expect(target.querySelectorAll('.seat-ring-pos--self .seat-ring-slot')).toHaveLength(1);
	});

	it('shows the self wind based on the dealer and seat', () => {
		const { target } = render(SeatRing, {
			you: 0,
			dealer: 0,
			seatStatus: ['connected', 'empty', 'empty', 'empty'],
			names: ['You', null, null, null]
		});
		const selfSlot = target.querySelector('.seat-ring-pos--self .seat-ring-slot');
		expect(selfSlot?.textContent).toContain('東');
	});

	it('rotates the wind label when you are not the dealer', () => {
		const { target } = render(SeatRing, {
			you: 1,
			dealer: 0,
			seatStatus: ['empty', 'connected', 'empty', 'empty'],
			names: [null, 'You', null, null]
		});
		const selfSlot = target.querySelector('.seat-ring-pos--self .seat-ring-slot');
		expect(selfSlot?.textContent).toContain('南');
	});

	it('maps other seats relative to the viewer', () => {
		const { target } = render(SeatRing, {
			you: 1,
			dealer: 0,
			seatStatus: ['connected', 'connected', 'connected', 'connected'],
			names: ['Across', 'You', 'Left', 'Right']
		});
		// seat indices relative to you=1: across=(1+2)%4=3, left=(1+3)%4=0, right=(1+1)%4=2
		expect(target.querySelector('.seat-ring-pos--across')?.textContent).toContain('Right');
		expect(target.querySelector('.seat-ring-pos--left')?.textContent).toContain('Across');
		expect(target.querySelector('.seat-ring-pos--right')?.textContent).toContain('Left');
	});
});
