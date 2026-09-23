import { describe, it, expect } from 'vitest';
import { createRawSnippet } from 'svelte';
import { render } from 'svelte/server';
import DismissablePanel from './DismissablePanel.svelte';

describe('DismissablePanel', () => {
	it('renders its children inside the panel', () => {
		const children = createRawSnippet(() => ({
			render: () => '<p>panel content</p>'
		}));
		const { body } = render(DismissablePanel, { props: { onClose: () => {}, children } });
		expect(body).toContain('panel content');
	});

	it('renders a close button', () => {
		const children = createRawSnippet(() => ({ render: () => '<p>x</p>' }));
		const { body } = render(DismissablePanel, { props: { onClose: () => {}, children } });
		expect(body).toContain('close-btn');
	});
});
