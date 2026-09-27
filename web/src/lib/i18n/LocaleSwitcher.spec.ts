import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import LocaleSwitcher from './LocaleSwitcher.svelte';

// `setLocale` firing on click is a thin wrapper around Paraglide's own runtime (untested
// elsewhere in this repo either) -- svelte/server only renders markup here.
describe('LocaleSwitcher', () => {
	it('renders one option per configured locale', () => {
		const { body } = render(LocaleSwitcher);
		expect([...body.matchAll(/type="radio"/g)]).toHaveLength(2);
	});

	it('labels each locale in its own language', () => {
		const { body } = render(LocaleSwitcher);
		expect(body).toContain('English');
		expect(body).toContain('繁體中文');
	});

	it('marks the base locale as checked by default', () => {
		const { body } = render(LocaleSwitcher);
		expect(body).toContain('value="en"');
		const enOption = body.split('value="en"')[1]?.split('</label>')[0] ?? '';
		expect(enOption).toContain('checked');
	});
});
