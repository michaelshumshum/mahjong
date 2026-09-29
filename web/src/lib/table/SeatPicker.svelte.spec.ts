import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatPicker from './SeatPicker.svelte';

describe('SeatPicker', () => {
	afterEach(cleanupAll);

	it('renders four pickable slots in the expected positions', () => {
		const { target } = render(SeatPicker, {
			seatStatus: ['empty', 'empty', 'empty', 'empty'],
			names: [null, null, null, null],
			onJoin: vi.fn()
		});
		expect(target.querySelectorAll('.seat-ring-pos')).toHaveLength(4);
		expect(target.querySelectorAll('button')).toHaveLength(4);
	});

	it('maps seats to fixed positions', () => {
		const { target } = render(SeatPicker, {
			seatStatus: ['connected', 'connected', 'connected', 'connected'],
			names: ['Self', 'Right', 'Across', 'Left'],
			onJoin: vi.fn()
		});
		expect(target.querySelector('.seat-ring-pos--across')?.textContent).toContain('Across');
		expect(target.querySelector('.seat-ring-pos--left')?.textContent).toContain('Left');
		expect(target.querySelector('.seat-ring-pos--right')?.textContent).toContain('Right');
		expect(target.querySelector('.seat-ring-pos--self')?.textContent).toContain('Self');
	});

	it('dispatches onJoin with the clicked seat', () => {
		const onJoin = vi.fn();
		const { target } = render(SeatPicker, {
			seatStatus: ['empty', 'empty', 'empty', 'empty'],
			names: [null, null, null, null],
			onJoin
		});
		target.querySelector<HTMLButtonElement>('.seat-ring-pos--across button')?.click();
		expect(onJoin).toHaveBeenCalledWith(2);

		target.querySelector<HTMLButtonElement>('.seat-ring-pos--left button')?.click();
		expect(onJoin).toHaveBeenCalledWith(3);

		target.querySelector<HTMLButtonElement>('.seat-ring-pos--right button')?.click();
		expect(onJoin).toHaveBeenCalledWith(1);

		target.querySelector<HTMLButtonElement>('.seat-ring-pos--self button')?.click();
		expect(onJoin).toHaveBeenCalledWith(0);
	});

	it('does not dispatch onJoin for occupied seats', () => {
		const onJoin = vi.fn();
		const { target } = render(SeatPicker, {
			seatStatus: ['connected', 'empty', 'empty', 'empty'],
			names: ['Alice', null, null, null],
			onJoin
		});
		target.querySelector<HTMLButtonElement>('.seat-ring-pos--self button')?.click();
		expect(onJoin).not.toHaveBeenCalled();
	});
});
