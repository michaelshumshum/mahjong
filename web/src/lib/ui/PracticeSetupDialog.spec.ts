import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import PracticeSetupDialog from './PracticeSetupDialog.svelte';

// Interaction is covered end-to-end (routes/page.e2e.ts); this file covers initial render only:
// labelled dialog, one seat-ring slot per bot seat, defaulting to Normal, human seat marked distinctly.
describe('PracticeSetupDialog', () => {
	const noop = () => {};

	it('renders as a labelled dialog', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('role="dialog"');
		expect(body).toContain('aria-modal="true"');
		expect(body).toContain('Practice vs Bots');
	});

	it('lays out the three bot seats in the same ring arrangement as the seat-selection screen', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('seat-ring-pos--across');
		expect(body).toContain('seat-ring-pos--left');
		expect(body).toContain('seat-ring-pos--right');
		expect(body).toContain('seat-ring-pos--self');
	});

	it('defaults every bot seat to Normal, and marks the human seat distinctly', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('Right opponent: Normal. Click to change.');
		expect(body).toContain('Across: Normal. Click to change.');
		expect(body).toContain('Left opponent: Normal. Click to change.');
		expect(body).toContain('You');
		expect(body).toContain('Your seat');
	});
});
