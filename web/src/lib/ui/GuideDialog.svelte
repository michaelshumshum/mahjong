<script lang="ts">
	import ModalDialog from './ModalDialog.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import CloseButton from './CloseButton.svelte';
	import PanelHeader from './PanelHeader.svelte';
	import TabBar from './TabBar.svelte';
	import GuidePatterns from './GuidePatterns.svelte';
	import GuideScoring from './GuideScoring.svelte';
	import HandChecker from './HandChecker.svelte';
	import { presetRules, scoredEntries } from './faan-guide';
	import {
		CUSTOM_PRESET_ID,
		DEFAULT_PRESET_ID,
		RULESET_PRESET_OPTIONS,
		type RuleSet
	} from '$lib/net/ruleset';

	type View = 'patterns' | 'scoring' | 'checker';
	const TABLE_CHOICE = 'table';
	const ALL_CHOICE = '';

	let {
		onClose,
		tableRules = null,
		tablePreset = null,
		focusPattern = null
	}: {
		onClose: () => void;
		// the table's own ruleset, when opened from a table
		tableRules?: RuleSet | null;
		tablePreset?: string | null;
		// open on this pattern
		focusPattern?: string | null;
	} = $props();

	let view = $state<View>('patterns');
	// seeded from props once: the dialog mounts per open
	// svelte-ignore state_referenced_locally
	let choice = $state(tableRules ? TABLE_CHOICE : ALL_CHOICE);
	// svelte-ignore state_referenced_locally
	let focus = $state<string | null>(focusPattern);

	let rules = $derived(choice === TABLE_CHOICE ? tableRules : presetRules(choice || null));
	let entries = $derived(scoredEntries(rules));

	// what POST /score resolves; "all rulesets" has no rules of its own, so it checks the default
	let checkerRuleset = $derived(
		choice === TABLE_CHOICE && tableRules
			? tablePreset
				? { ruleset: tablePreset }
				: { ruleset: CUSTOM_PRESET_ID, rules: tableRules }
			: { ruleset: choice || DEFAULT_PRESET_ID }
	);
	let checkerPresetLabel = $derived(
		choice === ALL_CHOICE
			? (RULESET_PRESET_OPTIONS.find((o) => o.id === DEFAULT_PRESET_ID)?.label() ?? '')
			: null
	);

	let views = $derived([
		{ id: 'patterns' as const, label: m.guide_viewPatterns() },
		{ id: 'scoring' as const, label: m.guide_viewScoring() },
		{ id: 'checker' as const, label: m.guide_viewChecker() }
	]);

	function openPattern(pattern: string): void {
		view = 'patterns';
		focus = pattern;
	}
</script>

<ModalDialog labelledby="guide-heading" onCancel={onClose}>
	<div class="guide-dialog" data-testid="guide-dialog">
		<CloseButton onclick={onClose} />
		<PanelHeader title={m.guide_title()} titleId="guide-heading" />

		<div class="context">
			<label class="filter">
				<span>{m.guide_rulesetLabel()}</span>
				<select data-testid="guide-ruleset" bind:value={choice}>
					{#if tableRules}
						<option value={TABLE_CHOICE}>{m.guide_rulesetTable()}</option>
					{/if}
					<option value={ALL_CHOICE}>{m.guide_rulesetAll()}</option>
					{#each RULESET_PRESET_OPTIONS as option (option.id)}
						<option value={option.id}>{option.label()}</option>
					{/each}
				</select>
			</label>
			{#if rules}
				<p class="summary" data-testid="guide-rules-summary">
					{m.guide_rulesSummary({
						min: rules.min_faan,
						cap: rules.faan_cap,
						table:
							rules.score_table === 'full_spicy'
								? m.createTableDialog_scoreTableFullSpicy()
								: m.createTableDialog_scoreTableHalfSpicy()
					})}
				</p>
			{/if}
		</div>

		<TabBar
			tabs={views}
			active={view}
			idPrefix="guide"
			label={m.guide_viewsLabel()}
			testidPrefix="guide-view"
			onChange={(next) => (view = next)}
		/>

		<div class="view" id="guide-panel-{view}" role="tabpanel" aria-labelledby="guide-tab-{view}">
			{#if view === 'patterns'}
				<GuidePatterns {entries} {rules} bind:focus />
			{:else if view === 'scoring'}
				<GuideScoring {rules} />
			{:else}
				{#if checkerPresetLabel}
					<p class="checker-preset">
						{m.guide_checkerScoredUnder({ ruleset: checkerPresetLabel })}
					</p>
				{/if}
				<HandChecker ruleset={checkerRuleset} onPatternSelect={openPattern} />
			{/if}
		</div>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/buttons';

	.guide-dialog {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: 100%;
		max-width: 40rem;
		height: 90dvh;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	.context {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-2) var(--space-4);
		flex-shrink: 0;
	}

	.filter {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		font-size: var(--font-size-sm);

		select {
			font: inherit;
			min-height: 36px;
			padding: var(--space-1) var(--space-2);
			color: var(--color-text);
			@include buttons.input-recessed;
		}
	}

	.summary,
	.checker-preset {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.summary {
		padding-block: var(--space-2);
	}

	.view {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		flex: 1;
		min-height: 0;
	}
</style>
