import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import ClaimButtons from './ClaimButtons.svelte';
import type { ClaimOption } from './ClaimButtons.svelte';

// `onChoose` firing on click is covered end-to-end (routes/page.e2e.ts) -- svelte/server only
// renders markup here. This file covers button count, labels, and chow disambiguation.
describe('ClaimButtons', () => {
	const noop = () => {};

	it('renders one button per option', () => {
		const options: ClaimOption[] = [{ kind: 'pung' }, { kind: 'win' }, { kind: 'pass' }];
		const { body } = render(ClaimButtons, { props: { options, onChoose: noop } });
		expect([...body.matchAll(/<button/g)]).toHaveLength(3);
	});

	it('labels plain-kind options without a tile suffix', () => {
		const options: ClaimOption[] = [{ kind: 'pung' }, { kind: 'kong' }, { kind: 'win' }];
		const { body } = render(ClaimButtons, { props: { options, onChoose: noop } });
		expect(body).toContain('>Pung<');
		expect(body).toContain('>Kong<');
		expect(body).toContain('>Win<');
		expect(body).not.toContain('aria-label="Pung');
	});

	it('disambiguates two simultaneous chow options by their claimed tiles', () => {
		const options: ClaimOption[] = [
			{ kind: 'chow', tiles: ['4s', '5s'] },
			{ kind: 'chow', tiles: ['5s', '7s'] }
		];
		const { body } = render(ClaimButtons, { props: { options, onChoose: noop } });
		expect(body).toContain('aria-label="Chow: 4 Bamboo, 5 Bamboo"');
		expect(body).toContain('aria-label="Chow: 5 Bamboo, 7 Bamboo"');
		expect([...body.matchAll(/data-tile="(\w+)"/g)].map((m) => m[1])).toEqual([
			'4s',
			'5s',
			'5s',
			'7s'
		]);
	});

	it('never shows raw tile codes as text, and previews a pung tile once', () => {
		const options: ClaimOption[] = [{ kind: 'pung', tiles: ['z5', 'z5'] }];
		const { body } = render(ClaimButtons, { props: { options, onChoose: noop } });
		expect(body).toContain('>Pung<');
		expect(body).not.toMatch(/>[^<]*z5[^<]*</);
		expect(body.match(/data-tile="z5"/g)).toHaveLength(1);
		expect(body).toContain('aria-label="Pung: Red Dragon"');
	});

	it('renders nothing when there are no options', () => {
		const { body } = render(ClaimButtons, { props: { options: [], onChoose: noop } });
		expect(body).not.toContain('<button');
	});
});
