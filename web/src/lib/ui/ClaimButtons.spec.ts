import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import ClaimButtons from './ClaimButtons.svelte';
import type { ClaimOption } from './ClaimButtons.svelte';

// `onChoose` firing on click is exercised end-to-end (routes/page.e2e.ts) against the demo
// section on `/` — svelte/server only renders markup, there's no DOM to dispatch a real click
// event against here. This file covers the render output: button count, labels, and the
// multi-chow-option disambiguation.
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
	});

	it('disambiguates two simultaneous chow options by their claimed tiles', () => {
		const options: ClaimOption[] = [
			{ kind: 'chow', tiles: ['4s', '5s'] },
			{ kind: 'chow', tiles: ['5s', '7s'] }
		];
		const { body } = render(ClaimButtons, { props: { options, onChoose: noop } });
		expect(body).toContain('>Chow 4s-5s<');
		expect(body).toContain('>Chow 5s-7s<');
	});

	it('renders nothing when there are no options', () => {
		const { body } = render(ClaimButtons, { props: { options: [], onChoose: noop } });
		expect(body).not.toContain('<button');
	});
});
