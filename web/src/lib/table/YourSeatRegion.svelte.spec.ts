import { describe, it, expect, afterEach, vi } from 'vitest';
import { flushSync } from 'svelte';
import { render, cleanupAll } from './test-render';
import YourSeatRegion from './YourSeatRegion.svelte';
import type { MockSeatState } from './mock-game-state';

function mockSeat(overrides: Partial<MockSeatState> = {}): MockSeatState {
	return {
		seat: 0,
		name: 'You',
		concealedCount: 2,
		melds: [],
		discards: [],
		flowers: [],
		score: 0,
		concealedHand: ['1m', '2m'],
		...overrides
	};
}

function baseProps(discardMode: 'two-step' | 'one-tap', onDiscard = vi.fn()) {
	return {
		seat: mockSeat(),
		spectating: false,
		dealer: 0 as const,
		turn: 0,
		isMock: false,
		ownHandTiles: [
			{ key: 'c-0', code: '1m' as const, tileId: 10, drawn: false },
			{ key: 'c-1', code: '2m' as const, tileId: 11, drawn: false }
		],
		discardableTileIds: new Set([10, 11]),
		discardMode,
		onDiscard,
		declareOptions: []
	};
}

describe('YourSeatRegion discard modes', () => {
	afterEach(() => {
		cleanupAll();
		vi.useRealTimers();
	});

	it('one-tap: a single click discards immediately', () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('one-tap', onDiscard));
		const first = target.querySelectorAll('.hand-tile-btn')[0] as HTMLButtonElement;
		first.click();
		flushSync();
		expect(onDiscard).toHaveBeenCalledWith(10);
		expect(first.classList.contains('hand-tile--pending')).toBe(true);
		expect(target.querySelector('.pending-spinner')).not.toBeNull();
	});

	it('two-step: first click lifts without discarding, second click discards', () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('two-step', onDiscard));
		const first = target.querySelectorAll('.hand-tile-btn')[0] as HTMLButtonElement;
		first.click();
		flushSync();
		expect(onDiscard).not.toHaveBeenCalled();
		expect(first.classList.contains('hand-tile--lifted')).toBe(true);
		first.click();
		flushSync();
		expect(onDiscard).toHaveBeenCalledWith(10);
		expect(first.classList.contains('hand-tile--lifted')).toBe(false);
	});

	it('two-step: clicking a different tile moves the lift to it', () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('two-step', onDiscard));
		const [first, second] = [...target.querySelectorAll('.hand-tile-btn')] as HTMLButtonElement[];
		first.click();
		flushSync();
		second.click();
		flushSync();
		expect(onDiscard).not.toHaveBeenCalled();
		expect(first.classList.contains('hand-tile--lifted')).toBe(false);
		expect(second.classList.contains('hand-tile--lifted')).toBe(true);
	});

	it('two-step: Escape clears the lift without discarding', () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('two-step', onDiscard));
		const first = target.querySelectorAll('.hand-tile-btn')[0] as HTMLButtonElement;
		first.click();
		flushSync();
		window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
		flushSync();
		expect(first.classList.contains('hand-tile--lifted')).toBe(false);
		expect(onDiscard).not.toHaveBeenCalled();
	});

	it('two-step: clicking outside the hand clears the lift without discarding', () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('two-step', onDiscard));
		const first = target.querySelectorAll('.hand-tile-btn')[0] as HTMLButtonElement;
		first.click();
		flushSync();
		document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }));
		flushSync();
		expect(first.classList.contains('hand-tile--lifted')).toBe(false);
		expect(onDiscard).not.toHaveBeenCalled();
	});

	it('shows a stalled indicator after the pending tile gets no echo in time', () => {
		vi.useFakeTimers();
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, baseProps('one-tap', onDiscard));
		const first = target.querySelectorAll('.hand-tile-btn')[0] as HTMLButtonElement;
		first.click();
		flushSync();
		expect(target.querySelector('.pending-spinner--stalled')).toBeNull();
		vi.advanceTimersByTime(3000);
		flushSync();
		expect(target.querySelector('.pending-spinner--stalled')).not.toBeNull();
	});
});
