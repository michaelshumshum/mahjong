import { describe, it, expect, afterEach, vi } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatPickerSlot from './SeatPickerSlot.svelte';

describe('SeatPickerSlot', () => {
	afterEach(cleanupAll);

	it('renders an open, clickable slot for an empty seat', () => {
		const { target } = render(SeatPickerSlot, {
			seat: 0,
			self: false,
			status: 'empty',
			name: null,
			onJoin: vi.fn()
		});
		const button = target.querySelector('button');
		expect(button).not.toBeNull();
		expect(button?.disabled).toBe(false);
		expect(button?.classList.contains('seat-ring-slot--open')).toBe(true);
		expect(button?.textContent).toContain('Open');
	});

	it('disables the button for an occupied seat', () => {
		const { target } = render(SeatPickerSlot, {
			seat: 1,
			self: false,
			status: 'connected',
			name: 'Alice',
			onJoin: vi.fn()
		});
		const button = target.querySelector('button');
		expect(button?.disabled).toBe(true);
		expect(button?.classList.contains('seat-ring-slot--open')).toBe(false);
		expect(button?.textContent).toContain('Alice');
	});

	it('labels a bot seat and disables it', () => {
		const { target } = render(SeatPickerSlot, {
			seat: 2,
			self: false,
			status: 'bot',
			name: null,
			onJoin: vi.fn()
		});
		const button = target.querySelector('button');
		expect(button?.disabled).toBe(true);
		expect(button?.textContent).toContain('Bot');
	});

	it('calls onJoin with the seat number when clicked', () => {
		const onJoin = vi.fn();
		const { target } = render(SeatPickerSlot, {
			seat: 3,
			self: false,
			status: 'empty',
			name: null,
			onJoin
		});
		target.querySelector('button')?.click();
		expect(onJoin).toHaveBeenCalledWith(3);
	});

	it('does not call onJoin when the slot is disabled', () => {
		const onJoin = vi.fn();
		const { target } = render(SeatPickerSlot, {
			seat: 1,
			self: false,
			status: 'connected',
			name: 'Alice',
			onJoin
		});
		target.querySelector('button')?.click();
		expect(onJoin).not.toHaveBeenCalled();
	});

	it('applies the self style to the self seat', () => {
		const { target } = render(SeatPickerSlot, {
			seat: 0,
			self: true,
			status: 'empty',
			name: null,
			onJoin: vi.fn()
		});
		expect(target.querySelector('.seat-ring-slot--self')).not.toBeNull();
	});
});
