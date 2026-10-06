import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from './test-render';
import SeatPlate from './SeatPlate.svelte';

describe('SeatPlate', () => {
	afterEach(cleanupAll);

	it('renders name, wind, and score', () => {
		const { target } = render(SeatPlate, {
			name: 'Bob',
			windChar: '南',
			windAriaLabel: 'South wind',
			isDealer: false,
			dealerTitle: 'Dealer',
			score: 25
		});
		expect(target.querySelector('.seat-name')?.textContent).toContain('Bob');
		expect(target.querySelector('.seat-wind')?.textContent).toContain('南');
		expect(target.querySelector('.seat-score')?.textContent).toContain('25');
		expect(target.querySelector('.dealer-badge')).toBeNull();
	});

	it('shows the dealer badge when isDealer is set', () => {
		const { target } = render(SeatPlate, {
			name: 'Bob',
			windChar: '東',
			windAriaLabel: 'East wind',
			isDealer: true,
			dealerTitle: 'Dealer',
			score: 0
		});
		expect(target.querySelector('.dealer-badge')?.textContent).toContain('莊');
	});

	it('adds the turn halo class only when isTurn is set', () => {
		const { target } = render(SeatPlate, {
			name: 'Bob',
			windChar: '東',
			windAriaLabel: 'East wind',
			isDealer: false,
			dealerTitle: 'Dealer',
			score: 0,
			isTurn: true
		});
		expect(target.querySelector('.seat-plate--turn')).not.toBeNull();
	});

	it('has no turn halo class by default', () => {
		const { target } = render(SeatPlate, {
			name: 'Bob',
			windChar: '東',
			windAriaLabel: 'East wind',
			isDealer: false,
			dealerTitle: 'Dealer',
			score: 0
		});
		expect(target.querySelector('.seat-plate--turn')).toBeNull();
	});
});
