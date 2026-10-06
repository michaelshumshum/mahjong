import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import TileFace from './TileFace.svelte';

describe('TileFace', () => {
	it('renders the matching face asset for a tile code', () => {
		const { body } = render(TileFace, { props: { code: '5s' } });
		expect(body).toContain('src="/tiles/Sou5.svg"');
	});

	it('renders honor/dragon faces from the same asset map', () => {
		const { body } = render(TileFace, { props: { code: 'z5' } });
		expect(body).toContain('src="/tiles/Chun.svg"');
	});

	it('renders flower/season faces from the same asset map', () => {
		const { body } = render(TileFace, { props: { code: 'f1' } });
		expect(body).toContain('src="/tiles/Flor1.svg"');
	});

	it('renders the tile back as CSS (no image asset) for a concealed (null) tile', () => {
		const { body } = render(TileFace, { props: { code: null } });
		expect(body).toMatch(/class="tile-face[^"]*\btile-face--back\b/);
		expect(body).not.toContain('<img');
		expect(body).toContain('concealed tile');
		expect(body).not.toContain('data-tile');
	});

	it('uses the localized tile name as alt text, never the raw code', () => {
		const { body } = render(TileFace, { props: { code: 'z5' } });
		expect(body).toContain('alt="Red Dragon"');
		expect(body).toContain('data-tile="z5"');
	});
});
