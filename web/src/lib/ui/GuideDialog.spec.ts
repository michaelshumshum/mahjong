import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import GuideDialog from './GuideDialog.svelte';
import { DEFAULT_RULESET } from '$lib/net/ruleset';

describe('GuideDialog', () => {
	it('renders a labelled dialog with three views and a filter per faan count', () => {
		const { body } = render(GuideDialog, { props: { onClose: () => {} } });
		expect(body).toContain('<dialog');
		expect(body).toContain('aria-labelledby="guide-heading"');
		expect(body).toContain('Faan guide');
		for (const t of ['all', '0', '1', '3', '4', '5', '6', '7', '8', 'limit'])
			expect(body).toContain(`data-testid="guide-tab-${t}"`);
		for (const v of ['patterns', 'scoring', 'checker'])
			expect(body).toContain(`data-testid="guide-view-${v}"`);
	});

	it('opens on every pattern with example tiles and a faan badge', () => {
		const { body } = render(GuideDialog, { props: { onClose: () => {} } });
		expect(body).toContain('All Sequences');
		expect(body).toContain('Thirteen Orphans');
		expect(body).toContain('/tiles/Man1.svg');
		expect(body).toContain('data-testid="guide-entry-faan"');
		expect(body).not.toContain('data-testid="guide-rules-summary"');
	});

	it('defaults to the table’s rules, overrides included', () => {
		const tableRules = { ...DEFAULT_RULESET, faan_overrides: { 清一色: 5 } };
		const { body } = render(GuideDialog, {
			props: { onClose: () => {}, tableRules, tablePreset: null }
		});
		expect(body).toContain('This table');
		expect(body).toContain('Min 3 faan · cap 10');
		expect(body).toContain('default 7');
		expect(body).not.toContain('Seven Pairs');
	});
});
