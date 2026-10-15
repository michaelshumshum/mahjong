import { describe, it, expect, afterEach } from 'vitest';
import { page } from 'vitest/browser';
import { render, cleanupAll } from './test-render';
import OpponentRegion from './OpponentRegion.svelte';
import type { MockSeatState } from './view-types';
import type { BotTier } from '$lib/net/protocol';

function mockSeat(overrides: Partial<MockSeatState> = {}): MockSeatState {
	return {
		seat: 1,
		name: 'Bob',
		concealedCount: 13,
		melds: [],
		discards: [],
		flowers: [],
		score: 0,
		...overrides
	};
}

describe('OpponentRegion', () => {
	afterEach(cleanupAll);

	it('renders the seat name, wind, and score', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ name: 'Bob', score: 25 }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.seat-name')?.textContent).toContain('Bob');
		expect(target.querySelector('.seat-score')?.textContent).toContain('25');
		expect(target.querySelector('.seat-wind')?.textContent).toContain('南');
	});

	it('applies the position modifier and turn highlight', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ seat: 2 }),
			position: 'left',
			dealer: 0,
			turn: 2
		});
		expect(target.querySelector('.seat-region--left')).not.toBeNull();
		expect(target.querySelector('.seat-region--turn')).not.toBeNull();
	});

	it('shows the dealer badge when the seat is the dealer', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ seat: 1 }),
			position: 'right',
			dealer: 1,
			turn: 0
		});
		expect(target.querySelector('.dealer-badge')).not.toBeNull();
		expect(target.querySelector('.dealer-badge')?.textContent).toContain('莊');
	});

	it('shows the bot badge for bot status', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'bot' }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.bot-badge')).not.toBeNull();
	});

	it("names the bot's level in its badge", () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'bot', botLevel: 'T4' }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		const badge = target.querySelector('.bot-badge');
		expect(badge?.textContent).toContain('Expert');
		expect(badge?.getAttribute('data-level')).toBe('T4');
	});

	it('falls back to a plain bot badge for an unknown level', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'bot', botLevel: 'T9' as BotTier }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.bot-badge')?.textContent?.trim()).toBe('Bot');
	});

	it('shows an away chip for a disconnected seat', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'disconnected' }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.status-chip--away')).not.toBeNull();
		expect(target.querySelector('.status-chip--autoplay')).toBeNull();
	});

	it('shows an autoplay chip when the server is playing a seat', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'autoplay' }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.status-chip--autoplay')).not.toBeNull();
		expect(target.querySelector('.status-chip--away')).toBeNull();
	});

	it('shows no status chip for a connected seat', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ status: 'connected' }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.status-chip')).toBeNull();
	});

	it('renders concealed backs when concealedHand is not provided', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ concealedCount: 10 }),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		const backs = target.querySelectorAll('.backs-row .mini-tile');
		expect(backs).toHaveLength(10);
		expect(target.querySelectorAll('.backs-row .tile-face--back').length).toBeGreaterThan(0);
	});

	it('carries a ×N count for the phone chip, and none for revealed hands', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ concealedCount: 13 }),
			position: 'right',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelector('.backs-row .backs-count')?.textContent).toBe('×13');
		const open = render(OpponentRegion, {
			seat: mockSeat({ concealedHand: ['1m'], concealedCount: 1 }),
			position: 'right',
			dealer: 0,
			turn: 0
		});
		expect(open.target.querySelector('.backs-count')).toBeNull();
	});

	it('renders revealed concealed tiles for spectators', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({ concealedHand: ['1m', '2m', '3m'], concealedCount: 3 }),
			position: 'left',
			dealer: 0,
			turn: 0
		});
		const tiles = target.querySelectorAll('.backs-row .mini-tile');
		expect(tiles).toHaveLength(3);
		expect(target.innerHTML).toContain('src="/tiles/Man1.svg"');
	});

	it('renders flowers and melds', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat({
				flowers: ['f1'],
				melds: [
					{ kind: 'pung', tiles: ['z1', 'z1', 'z1'], fromSeat: 3 },
					{ kind: 'concealed_kong', tiles: ['z7', 'z7', 'z7', 'z7'] }
				]
			}),
			position: 'right',
			dealer: 0,
			turn: 0
		});
		expect(target.querySelectorAll('.meld-row .mini-tile')).toHaveLength(8);
		// concealed kong: end tiles as backs, middle two face-up
		expect(target.querySelectorAll('.meld-row .tile-face--back')).toHaveLength(2);
		expect(target.querySelectorAll('.meld-row [data-tile="z7"]')).toHaveLength(2);
	});

	// first meld/flower must not grow the region and shift the centre discard box.
	it('reserves the meld row while the seat has no melds or flowers', () => {
		const { target } = render(OpponentRegion, {
			seat: mockSeat(),
			position: 'across',
			dealer: 0,
			turn: 0
		});
		const row = target.querySelector<HTMLElement>('.meld-row');
		expect(row).not.toBeNull();
		expect(row!.classList.contains('meld-row--empty')).toBe(true);
		expect(parseFloat(getComputedStyle(row!).minBlockSize)).toBeGreaterThan(0);
	});

	// the seat's own left: across faces down the screen, left faces right, right faces left.
	for (const [position, edge] of [
		['across', 'right'],
		['left', 'top'],
		['right', 'bottom']
	] as const) {
		it(`aligns the ${position} seat's melds to its own left at tablet-up`, async () => {
			await page.viewport(1024, 768);
			const { target } = render(OpponentRegion, {
				seat: mockSeat({
					concealedCount: 4,
					flowers: ['f1'],
					melds: [{ kind: 'pung', tiles: ['1m', '1m', '1m'] }]
				}),
				position,
				dealer: 0,
				turn: 0
			});
			// the table grid sizes the region in the app; give the side strips room to run.
			target.querySelector<HTMLElement>('.seat-region')!.style.height = '600px';
			const strip = target.querySelector('.seat-hand-strip')!.getBoundingClientRect();
			const row = target.querySelector('.meld-row')!.getBoundingClientRect();
			expect(Math.abs(row[edge] - strip[edge])).toBeLessThanOrEqual(1);
			const backs = target.querySelector('.backs-row')!.getBoundingClientRect();
			expect(Math.abs(backs[edge] - strip[edge])).toBeGreaterThan(10);
		});
	}
});
