import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import GuideDialog from './GuideDialog.svelte';

describe('GuideDialog', () => {
	it('renders a labelled dialog with one tab per faan count plus limit', () => {
		const { body } = render(GuideDialog, { props: { onClose: () => {} } });
		expect(body).toContain('role="dialog"');
		expect(body).toContain('Faan guide');
		for (const t of ['1', '3', '4', '5', '6', '7', '8', 'limit'])
			expect(body).toContain(`data-testid="guide-tab-${t}"`);
	});

	it('opens on the 1 faan tab with example tiles', () => {
		const { body } = render(GuideDialog, { props: { onClose: () => {} } });
		expect(body).toContain('All Sequences');
		expect(body).toContain('/tiles/Man1.svg');
	});
});
