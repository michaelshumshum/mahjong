import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatOccupancySlot from './SeatOccupancySlot.svelte';

describe('SeatOccupancySlot', () => {
	afterEach(cleanupAll);

	it('renders an open slot without the filled modifier', () => {
		const { target } = render(SeatOccupancySlot, { status: 'empty', name: null });
		expect(target.querySelector('.seat-ring-slot')).not.toBeNull();
		expect(target.querySelector('.seat-ring-slot--filled')).toBeNull();
	});

	it('renders a player name for an occupied seat', () => {
		const { target } = render(SeatOccupancySlot, { status: 'connected', name: 'Alice' });
		expect(target.querySelector('.seat-ring-slot--filled')).not.toBeNull();
		expect(target.textContent).toContain('Alice');
	});

	it('renders a bot label for bot status', () => {
		const { target } = render(SeatOccupancySlot, { status: 'bot', name: null });
		expect(target.querySelector('.seat-ring-slot--filled')).not.toBeNull();
		expect(target.textContent).toContain('Bot');
	});

	it('falls back to a taken label when a name is missing', () => {
		const { target } = render(SeatOccupancySlot, { status: 'connected', name: null });
		expect(target.querySelector('.seat-ring-slot--filled')).not.toBeNull();
		expect(target.textContent).toContain('Taken');
	});
});
