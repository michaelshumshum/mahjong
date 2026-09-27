import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import PracticeSetupDialog from './PracticeSetupDialog.svelte';

// Interaction (submitting, sending the chosen tiers) is covered end-to-end
// (routes/page.e2e.ts) -- this file covers the initial render: labelled dialog, one picker per
// bot seat, defaulting to Normal.
describe('PracticeSetupDialog', () => {
	const noop = () => {};

	it('renders as a labelled dialog', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('role="dialog"');
		expect(body).toContain('aria-modal="true"');
		expect(body).toContain('Practice vs Bots');
	});

	it('offers a difficulty picker for each of the three bot seats, none for the human seat', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('Right opponent');
		expect(body).toContain('Across');
		expect(body).toContain('Left opponent');
		expect(body).not.toContain('seat-0-difficulty');
	});

	it('offers Easy/Normal/Impossible for every seat, defaulting to Normal', () => {
		const { body } = render(PracticeSetupDialog, { props: { onCreated: noop, onCancel: noop } });
		expect(body).toContain('Easy');
		expect(body).toContain('Normal');
		expect(body).toContain('Impossible');
		for (const seat of [1, 2, 3]) {
			expect(body).toMatch(
				new RegExp(`name="seat-${seat}-difficulty"[^>]*value="normal"[^>]*checked`)
			);
			expect(body).not.toMatch(
				new RegExp(`name="seat-${seat}-difficulty"[^>]*value="easy"[^>]*checked`)
			);
			expect(body).not.toMatch(
				new RegExp(`name="seat-${seat}-difficulty"[^>]*value="impossible"[^>]*checked`)
			);
		}
	});
});
