import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import ClaimDialog from './ClaimDialog.svelte';
import type { ClaimOption } from './ClaimButtons.svelte';

describe('ClaimDialog', () => {
	const noop = () => {};

	it('names the discarder and the claimed tile in the subtitle', () => {
		const options: ClaimOption[] = [{ kind: 'pung', tiles: ['z5', 'z5'] }, { kind: 'pass' }];
		const { body } = render(ClaimDialog, {
			props: {
				discardTile: 'z5',
				discarderName: 'Bob',
				options,
				durationMs: 5000,
				onChoose: noop
			}
		});
		expect(body).toContain('Bob discarded');
		expect(body).toContain('alt="Red Dragon"');
	});

	it('falls back to a generic subtitle when the discarder name is unknown', () => {
		const options: ClaimOption[] = [{ kind: 'win' }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: 'z5', discarderName: null, options, durationMs: 5000, onChoose: noop }
		});
		expect(body).toContain('Someone discarded');
	});

	// `.claim-meld-tile` wrapper immediately followed by its TileFace `data-tile` -- scopes the match to
	// meld-preview tiles only; the "X discarded" subtitle uses a differently-classed wrapper.
	function meldTileCodes(body: string): string[] {
		return [...body.matchAll(/class="claim-meld-tile[^"]*"><span[^>]*data-tile="(\ds)"/g)].map(
			(m) => m[1]
		);
	}

	it('previews a pung meld as the two hand tiles plus the claimed discard, with the claimed one marked', () => {
		const options: ClaimOption[] = [{ kind: 'pung', tiles: ['z5', 'z5'] }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: 'z5', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body.match(/data-tile="z5"/g)).toHaveLength(4); // 1 subtitle + 3 meld tiles
		expect([...body.matchAll(/claim-meld-tile--claimed/g)]).toHaveLength(1);
	});

	it('previews a chow meld sorted ascending regardless of option.tiles order', () => {
		const options: ClaimOption[] = [{ kind: 'chow', tiles: ['7s', '8s'] }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: '6s', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(meldTileCodes(body)).toEqual(['6s', '7s', '8s']);
	});

	it('renders no meld preview for win or pass', () => {
		const options: ClaimOption[] = [{ kind: 'win' }, { kind: 'pass' }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: 'z5', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body).not.toContain('claim-meld-tile');
	});

	it('renders no subtitle or meld previews when the claimed tile is unknown', () => {
		const options: ClaimOption[] = [{ kind: 'pung', tiles: ['z5', 'z5'] }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: null, discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body).not.toContain('discarded');
		expect(body).not.toContain('claim-meld-tile');
	});

	it('still labels the choose buttons plainly, matching claimOptionLabel', () => {
		const options: ClaimOption[] = [
			{ kind: 'chow', tiles: ['4s', '5s'] },
			{ kind: 'chow', tiles: ['5s', '7s'] },
			{ kind: 'pass' }
		];
		const { body } = render(ClaimDialog, {
			props: { discardTile: '6s', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body.match(/class="claim-btn-label[^"]*">Chow</g)).toHaveLength(2);
		expect(body).toContain('aria-label="Chow: 4 Bamboo, 5 Bamboo"');
		expect(body).toContain('aria-label="Chow: 5 Bamboo, 7 Bamboo"');
		expect(body).toMatch(/class="claim-btn-label[^"]*">Pass</);
		expect(body).toContain('claim-btn--pass');
	});

	it('shows a CJK glyph and a sub-label for pung/chow/kong/win, not for pass', () => {
		const options: ClaimOption[] = [
			{ kind: 'pung', tiles: ['z5', 'z5'] },
			{ kind: 'win' },
			{ kind: 'pass' }
		];
		const { body } = render(ClaimDialog, {
			props: { discardTile: 'z5', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body).toMatch(/class="claim-btn-glyph[^"]*"[^>]*>碰</);
		expect(body).toMatch(/class="claim-btn-glyph[^"]*"[^>]*>食糊</);
		expect(body).not.toMatch(/claim-btn--pass[\s\S]*?claim-btn-glyph/);
		expect(body).toContain('claim-btn-sublabel');
	});

	it('shows a 1-based key hint on every option and an Esc hint on pass', () => {
		const options: ClaimOption[] = [{ kind: 'pung', tiles: ['z5', 'z5'] }, { kind: 'pass' }];
		const { body } = render(ClaimDialog, {
			props: { discardTile: 'z5', discarderName: 'Bob', options, durationMs: 5000, onChoose: noop }
		});
		expect(body).toMatch(/class="claim-btn-key[^"]*"[^>]*>1</);
		expect(body).toMatch(/class="claim-btn-key[^"]*"[^>]*>Esc</);
	});
});
