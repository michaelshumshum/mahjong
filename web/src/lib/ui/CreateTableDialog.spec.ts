import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import CreateTableDialog from './CreateTableDialog.svelte';

// Interaction is covered end-to-end (routes/page.e2e.ts) -- this file covers the initial
// render: sensible defaults, custom form hidden until chosen.
describe('CreateTableDialog', () => {
	const noop = () => {};

	it('renders as a labelled dialog', () => {
		const { body } = render(CreateTableDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('<dialog');
		expect(body).toContain('aria-labelledby="create-table-heading"');
		expect(body).toContain('Create a table');
	});

	it('defaults to the HK Classic preset selected, others not', () => {
		const { body } = render(CreateTableDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toMatch(/value="hk_classic"[^>]*checked/);
		expect(body).not.toMatch(/value="hk_casual"[^>]*checked/);
		expect(body).not.toMatch(/value="hk_strict"[^>]*checked/);
		expect(body).not.toMatch(/value="custom"[^>]*checked/);
	});

	it('describes each preset under its label', () => {
		const { body } = render(CreateTableDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('3 faan to win, capped at 10');
		expect(body).toContain('Set every rule yourself.');
	});

	it('hides the custom rules form until "Custom" is selected', () => {
		const { body } = render(CreateTableDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).not.toContain('Minimum faan');
		expect(body).not.toContain('Faan overrides');
	});

	it('offers every named preset plus custom', () => {
		const { body } = render(CreateTableDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('HK Classic');
		expect(body).toContain('Casual');
		expect(body).toContain('Strict');
		expect(body).toContain('Custom');
	});
});
