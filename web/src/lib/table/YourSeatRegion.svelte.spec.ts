import { describe, it, expect, afterEach, vi } from 'vitest';
import { page, userEvent } from 'vitest/browser';
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

describe('YourSeatRegion keyboard hand model', () => {
	afterEach(cleanupAll);

	function threeTileProps(discardMode: 'two-step' | 'one-tap', onDiscard = vi.fn()) {
		return {
			...baseProps(discardMode, onDiscard),
			ownHandTiles: [
				{ key: 'c-0', code: '1m' as const, tileId: 10, drawn: false },
				{ key: 'c-1', code: '2m' as const, tileId: 11, drawn: false },
				{ key: 'd', code: '3m' as const, tileId: 12, drawn: true }
			],
			discardableTileIds: new Set([10, 11, 12])
		};
	}

	function buttons(target: HTMLElement): HTMLButtonElement[] {
		return [...target.querySelectorAll<HTMLButtonElement>('.hand-tile-btn')];
	}

	it('is a single tab stop, defaulting to the drawn tile', () => {
		const { target } = render(YourSeatRegion, threeTileProps('two-step'));
		flushSync();
		expect(buttons(target).map((b) => b.tabIndex)).toEqual([-1, -1, 0]);
	});

	it('moves focus with arrows, Home and End, carrying the tab stop along', async () => {
		const { target } = render(YourSeatRegion, threeTileProps('two-step'));
		flushSync();
		const [first, second, drawn] = buttons(target);
		drawn.focus();
		await userEvent.keyboard('{ArrowLeft}');
		expect(document.activeElement).toBe(second);
		await userEvent.keyboard('{Home}');
		expect(document.activeElement).toBe(first);
		await userEvent.keyboard('{ArrowLeft}');
		expect(document.activeElement).toBe(first);
		flushSync();
		expect(buttons(target).map((b) => b.tabIndex)).toEqual([0, -1, -1]);
		await userEvent.keyboard('{End}');
		expect(document.activeElement).toBe(drawn);
		await userEvent.keyboard('{ArrowRight}');
		expect(document.activeElement).toBe(drawn);
	});

	it('two-step: Enter lifts the focused tile, a second Enter discards it', async () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, threeTileProps('two-step', onDiscard));
		flushSync();
		buttons(target)[2].focus();
		await userEvent.keyboard('{ArrowLeft}');
		await userEvent.keyboard('{Enter}');
		flushSync();
		expect(onDiscard).not.toHaveBeenCalled();
		expect(buttons(target)[1].classList.contains('hand-tile--lifted')).toBe(true);
		await userEvent.keyboard('{Enter}');
		expect(onDiscard).toHaveBeenCalledExactlyOnceWith(11);
	});

	it('two-step: Space lifts, Escape clears the lift', async () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, threeTileProps('two-step', onDiscard));
		flushSync();
		buttons(target)[0].focus();
		await userEvent.keyboard(' ');
		flushSync();
		expect(buttons(target)[0].classList.contains('hand-tile--lifted')).toBe(true);
		await userEvent.keyboard('{Escape}');
		flushSync();
		expect(buttons(target)[0].classList.contains('hand-tile--lifted')).toBe(false);
		expect(onDiscard).not.toHaveBeenCalled();
	});

	it('one-tap: Enter discards the focused tile immediately', async () => {
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, threeTileProps('one-tap', onDiscard));
		flushSync();
		buttons(target)[0].focus();
		await userEvent.keyboard('{Enter}');
		expect(onDiscard).toHaveBeenCalledExactlyOnceWith(10);
	});

	it('H jumps focus to the hand, but not while typing in an input', async () => {
		const { target } = render(YourSeatRegion, threeTileProps('two-step'));
		flushSync();
		const input = document.createElement('input');
		document.body.appendChild(input);
		input.focus();
		await userEvent.keyboard('h');
		expect(document.activeElement).toBe(input);
		expect(input.value).toBe('h');
		input.remove();

		document.body.focus();
		await userEvent.keyboard('h');
		expect(document.activeElement).toBe(buttons(target)[2]);
	});

	it('H focuses the hand row itself when no tile is discardable', async () => {
		const { target } = render(YourSeatRegion, {
			...threeTileProps('two-step'),
			discardableTileIds: new Set<number>()
		});
		flushSync();
		await userEvent.keyboard('H');
		expect(document.activeElement).toBe(target.querySelector('.hand-row'));
	});
});

describe('YourSeatRegion portrait phone two-row hand', () => {
	afterEach(() => {
		cleanupAll();
	});

	it('a lifted second-row tile does not take taps meant for the tile above it', async () => {
		await page.viewport(390, 844);
		// app.scss's tokens aren't loaded in a component spec; the hand's width calc needs these.
		for (const [name, value] of [
			['--space-1', '0.25rem'],
			['--space-2', '0.5rem'],
			['--space-4', '1rem']
		])
			document.documentElement.style.setProperty(name, value);
		const codes = [
			'1m',
			'2m',
			'3m',
			'4m',
			'5m',
			'6m',
			'7m',
			'8m',
			'9m',
			'1p',
			'2p',
			'3p',
			'4p',
			'5p'
		] as const;
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, {
			...baseProps('two-step', onDiscard),
			ownHandTiles: codes.map((code, i) => ({ key: `c-${i}`, code, tileId: i, drawn: i === 13 })),
			discardableTileIds: new Set(codes.map((_, i) => i))
		});
		const btns = [...target.querySelectorAll<HTMLButtonElement>('.hand-tile-btn')];
		const above = btns[1].getBoundingClientRect();
		const below = btns[9].getBoundingClientRect();
		expect(below.top).toBeGreaterThan(above.top);
		expect(below.top - above.bottom).toBeLessThanOrEqual(3);

		btns[9].click();
		flushSync();
		expect(btns[9].classList.contains('hand-tile--lifted')).toBe(true);
		expect(btns[9].getBoundingClientRect().top).toBeLessThan(above.bottom);

		const x = above.left + above.width / 2;
		const hit = (y: number) => document.elementFromPoint(x, y)?.closest('.hand-tile-btn');
		expect(hit(above.bottom - 2)).toBe(btns[1]);
		expect(hit(below.top + below.height / 2)).toBe(btns[9]);
		expect(onDiscard).not.toHaveBeenCalled();
	});
});

describe('YourSeatRegion spectator hand', () => {
	afterEach(() => {
		cleanupAll();
	});

	for (const faceUp of [true, false]) {
		it(`centres the bottom seat's ${faceUp ? 'face-up' : 'face-down'} hand at tablet-up`, async () => {
			await page.viewport(1024, 768);
			const { target } = render(YourSeatRegion, {
				...baseProps('two-step'),
				seat: mockSeat({ concealedHand: faceUp ? ['1m', '2m'] : undefined }),
				spectating: true,
				ownHandTiles: [],
				discardableTileIds: new Set<number>()
			});
			const row = target.querySelector<HTMLElement>('.backs-row')!;
			const tiles = row.querySelectorAll('.mini-tile');
			const r = row.getBoundingClientRect();
			const left = tiles[0].getBoundingClientRect().left - r.left;
			const right = r.right - tiles[tiles.length - 1].getBoundingClientRect().right;
			expect(left).toBeGreaterThan(10);
			expect(Math.abs(left - right)).toBeLessThanOrEqual(1);
		});
	}

	for (const [status, chip] of [
		['autoplay', '.status-chip--autoplay'],
		['disconnected', '.status-chip--away']
	] as const) {
		it(`shows the ${status} chip on the bottom seat`, () => {
			const { target } = render(YourSeatRegion, {
				...baseProps('two-step'),
				seat: mockSeat({ status }),
				spectating: true,
				ownHandTiles: [],
				discardableTileIds: new Set<number>()
			});
			expect(target.querySelector(chip)).not.toBeNull();
		});
	}

	it('shows no status chip on your own seat', () => {
		const { target } = render(YourSeatRegion, {
			...baseProps('two-step'),
			seat: mockSeat({ status: 'autoplay' })
		});
		expect(target.querySelector('.status-chip')).toBeNull();
	});
});

describe('YourSeatRegion manual hand order', () => {
	afterEach(cleanupAll);

	function arrangeProps(arrangeable: boolean, onReorder = vi.fn(), onDiscard = vi.fn()) {
		return {
			...baseProps('one-tap', onDiscard),
			ownHandTiles: [
				{ key: 't-10', code: '1m' as const, tileId: 10, drawn: false },
				{ key: 't-11', code: '2m' as const, tileId: 11, drawn: false },
				{ key: 't-12', code: '3m' as const, tileId: 12, drawn: true }
			],
			discardableTileIds: new Set([10, 11, 12]),
			arrangeable,
			onReorder
		};
	}

	function pointer(type: string, target: EventTarget, x: number, y: number): void {
		target.dispatchEvent(
			new PointerEvent(type, {
				bubbles: true,
				pointerId: 1,
				isPrimary: true,
				button: 0,
				clientX: x,
				clientY: y
			})
		);
	}

	function dragFirstOntoSecond(target: HTMLElement): void {
		const [first, second] = target.querySelectorAll<HTMLButtonElement>('.hand-tile-btn');
		const from = first.getBoundingClientRect();
		const to = second.getBoundingClientRect();
		const y = from.top + from.height / 2;
		pointer('pointerdown', first, from.left + from.width / 2, y);
		pointer('pointermove', document, from.left + from.width / 2 + 10, y);
		pointer('pointermove', document, to.left + to.width / 2 + 4, y);
		pointer('pointerup', document, to.left + to.width / 2 + 4, y);
		first.click();
		flushSync();
	}

	it('dragging a tile past a neighbour reorders it and swallows the release click', () => {
		const onReorder = vi.fn();
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, arrangeProps(true, onReorder, onDiscard));
		flushSync();
		dragFirstOntoSecond(target);
		expect(onReorder).toHaveBeenCalledWith(10, 1);
		expect(onDiscard).not.toHaveBeenCalled();
	});

	it('a short press stays a tap', () => {
		const onReorder = vi.fn();
		const onDiscard = vi.fn();
		const { target } = render(YourSeatRegion, arrangeProps(true, onReorder, onDiscard));
		flushSync();
		const first = target.querySelector<HTMLButtonElement>('.hand-tile-btn')!;
		const box = first.getBoundingClientRect();
		pointer('pointerdown', first, box.left + 5, box.top + 5);
		pointer('pointermove', document, box.left + 8, box.top + 6);
		pointer('pointerup', document, box.left + 8, box.top + 6);
		first.click();
		flushSync();
		expect(onReorder).not.toHaveBeenCalled();
		expect(onDiscard).toHaveBeenCalledWith(10);
	});

	it('never drags when auto-sorted', () => {
		const onReorder = vi.fn();
		const { target } = render(YourSeatRegion, arrangeProps(false, onReorder));
		flushSync();
		dragFirstOntoSecond(target);
		expect(onReorder).not.toHaveBeenCalled();
	});

	it('Shift+Arrow moves the focused tile one place', async () => {
		const onReorder = vi.fn();
		const { target } = render(YourSeatRegion, arrangeProps(true, onReorder));
		flushSync();
		target.querySelector<HTMLButtonElement>('.hand-tile-btn')!.focus();
		await userEvent.keyboard('{Shift>}{ArrowRight}{/Shift}');
		expect(onReorder).toHaveBeenCalledWith(10, 1);
	});
});
