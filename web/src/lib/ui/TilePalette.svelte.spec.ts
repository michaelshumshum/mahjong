import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanupAll, render } from '$lib/table/test-render';
import type { TileCode } from '$lib/table/tile-code';
import TilePalette from './TilePalette.svelte';

afterEach(cleanupAll);

function buttons(target: HTMLElement): HTMLButtonElement[] {
	return [...target.querySelectorAll<HTMLButtonElement>('button')];
}

describe('TilePalette', () => {
	it('shows every playable face plus the flowers by default', () => {
		const { target } = render(TilePalette, {
			label: 'Tiles',
			tileLabel: (code: TileCode) => `add ${code}`,
			onPick: () => {}
		});
		expect(buttons(target)).toHaveLength(34 + 8);
		expect(target.querySelector('[role="group"]')?.getAttribute('aria-label')).toBe('Tiles');
	});

	it('leaves the flowers out on request', () => {
		const { target } = render(TilePalette, {
			label: 'Tiles',
			tileLabel: (code: TileCode) => code,
			onPick: () => {},
			flowers: false
		});
		expect(buttons(target)).toHaveLength(34);
	});

	it('picks through onPick and disables what canPick refuses', () => {
		const onPick = vi.fn();
		const { target } = render(TilePalette, {
			label: 'Tiles',
			tileLabel: (code: TileCode) => code,
			onPick,
			canPick: (code: TileCode) => code !== '1m',
			testidPrefix: 'pick-'
		});
		const oneMan = target.querySelector<HTMLButtonElement>('[data-testid="pick-1m"]')!;
		const fiveSou = target.querySelector<HTMLButtonElement>('[data-testid="pick-5s"]')!;
		expect(oneMan.disabled).toBe(true);
		fiveSou.click();
		expect(onPick).toHaveBeenCalledWith('5s');
	});

	it('marks the selected tiles as pressed toggles only when a selection is given', () => {
		const plain = render(TilePalette, {
			label: 'Tiles',
			tileLabel: (code: TileCode) => code,
			onPick: () => {}
		});
		expect(buttons(plain.target).some((b) => b.hasAttribute('aria-pressed'))).toBe(false);

		const { target } = render(TilePalette, {
			label: 'Tiles',
			tileLabel: (code: TileCode) => code,
			onPick: () => {},
			selected: new Set<TileCode>(['3p', 'z5'])
		});
		const pressed = buttons(target)
			.filter((b) => b.getAttribute('aria-pressed') === 'true')
			.map((b) => b.getAttribute('aria-label'));
		expect(pressed).toEqual(['3p', 'z5']);
		expect(buttons(target).filter((b) => b.getAttribute('aria-pressed') === 'false')).toHaveLength(
			40
		);
	});
});
