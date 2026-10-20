<script lang="ts">
	import { tick } from 'svelte';
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';
	import SlidersHorizontal from '@lucide/svelte/icons/sliders-horizontal';
	import ModalDialog from './ModalDialog.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { createTable, type CreateTableRequest } from '$lib/net/lobby';
	import {
		CUSTOM_PRESET_ID,
		DEFAULT_PRESET_ID,
		RULESET_PRESET_OPTIONS,
		RULESET_PRESET_RULES,
		countRuleChanges,
		invalidRuleFields,
		withInertDefaults,
		type RuleSet
	} from '$lib/net/ruleset';
	import PanelHeader from './PanelHeader.svelte';
	import FormGroup from './FormGroup.svelte';
	import OptionRow from './OptionRow.svelte';
	import SwitchRow from './SwitchRow.svelte';
	import SegmentedControl from './SegmentedControl.svelte';
	import RulesEditor, { type OverrideRow, type RulesTab } from './RulesEditor.svelte';
	import { loadCreateTableSetup, saveCreateTableSetup } from './settings-storage';

	let { onCreated, onCancel }: { onCreated: (tableId: string) => void; onCancel: () => void } =
		$props();

	interface Draft {
		base: string;
		rules: RuleSet;
		overrides: OverrideRow[];
	}

	function draftFrom(base: string, source: RuleSet): Draft {
		const { faan_overrides, ...rest } = source;
		return {
			base,
			rules: { ...rest, hand_sets: [...rest.hand_sets], faan_overrides: {} },
			overrides: Object.entries(faan_overrides).map(([pattern, value]) => ({ pattern, value }))
		};
	}

	const saved = loadCreateTableSetup();
	let presetId = $state(saved?.presetId ?? DEFAULT_PRESET_ID);
	let draft = $state<Draft>(
		saved
			? draftFrom(saved.customBase, saved.custom)
			: draftFrom(DEFAULT_PRESET_ID, RULESET_PRESET_RULES[DEFAULT_PRESET_ID])
	);
	let isPrivate = $state(saved?.private ?? false);
	let view = $state<'presets' | 'custom'>('presets');
	let activeTab = $state<RulesTab>('scoring');
	// the draft a "Start from"/Reset just replaced, offered back until the next edit
	let replaced = $state<{ draft: Draft; preset: string } | null>(null);
	let submitting = $state(false);
	let scrollEl: HTMLElement | undefined = $state();
	let error = $state<string | null>(null);

	const customRules = $derived<RuleSet>({
		...draft.rules,
		faan_overrides: Object.fromEntries(draft.overrides.map((r) => [r.pattern, r.value as number]))
	});
	const baseRules = $derived(RULESET_PRESET_RULES[draft.base]);
	const changes = $derived(countRuleChanges(customRules, baseRules));
	const invalid = $derived(invalidRuleFields(customRules));
	const isCustom = $derived(presetId === CUSTOM_PRESET_ID);
	const presetLabel = (id: string) =>
		RULESET_PRESET_OPTIONS.find((o) => o.id === id)?.label() ?? id;

	const undoable = $derived(changes === 0 ? replaced : null);

	function openCustom(): void {
		presetId = CUSTOM_PRESET_ID;
		view = 'custom';
		error = null;
	}

	function loadPreset(id: string): void {
		const previous = $state.snapshot(draft) as Draft;
		const discarded = changes > 0 || previous.base !== id;
		draft = draftFrom(id, RULESET_PRESET_RULES[id]);
		replaced = discarded ? { draft: previous, preset: id } : null;
	}

	function undoReplace(): void {
		if (!replaced) return;
		draft = replaced.draft;
		replaced = null;
	}

	function firstInvalidTab(): RulesTab {
		if (invalid.some((f) => f === 'hand_sets' || f.startsWith('faan_overrides'))) return 'hands';
		if (invalid.includes('wall_reserve')) return 'play';
		return 'table';
	}

	async function handleSubmit(): Promise<void> {
		if (isCustom && invalid.length > 0) {
			view = 'custom';
			activeTab = firstInvalidTab();
			error = m.createTableDialog_fixErrors();
			await tick();
			const target = scrollEl?.querySelector<HTMLElement>(
				'[role="tabpanel"]:not([hidden]) :is([aria-invalid="true"], [role="alert"])'
			);
			target?.scrollIntoView({ block: 'center' });
			if (target?.matches('input')) target.focus();
			return;
		}
		submitting = true;
		error = null;
		const custom = withInertDefaults($state.snapshot(customRules) as RuleSet);
		const body: CreateTableRequest = isCustom
			? { ruleset: CUSTOM_PRESET_ID, rules: custom, private: isPrivate }
			: { ruleset: presetId, private: isPrivate };
		try {
			const response = await createTable(body);
			saveCreateTableSetup({ presetId, customBase: draft.base, custom, private: isPrivate });
			onCreated(response.table_id);
		} catch {
			error = m.createTableDialog_createError();
			submitting = false;
		}
	}
</script>

<ModalDialog labelledby="create-table-heading" onCancel={() => !submitting && onCancel()}>
	<div
		class="create-dialog"
		class:create-dialog--custom={view === 'custom'}
		data-testid="create-table-dialog"
	>
		{#if view === 'presets'}
			<PanelHeader title={m.createTableDialog_title()} titleId="create-table-heading" />

			<div class="body">
				<FormGroup legend={m.createTableDialog_rulesLegend()}>
					{#each RULESET_PRESET_OPTIONS as option (option.id)}
						<OptionRow
							type="radio"
							name="preset"
							value={option.id}
							label={option.label()}
							description={option.description()}
							checked={presetId === option.id}
							onChange={() => (presetId = option.id)}
						/>
					{/each}
					<OptionRow
						type="radio"
						name="preset"
						value={CUSTOM_PRESET_ID}
						label={m.createTableDialog_customLabel()}
						description={changes > 0
							? m.createTableDialog_customSummary({
									preset: presetLabel(draft.base),
									count: changes
								})
							: m.createTableDialog_customDescription()}
						checked={isCustom}
						onChange={openCustom}
					/>
				</FormGroup>
				{#if isCustom}
					<button
						type="button"
						class="edit-custom"
						data-testid="create-table-edit-custom"
						onclick={openCustom}
						><SlidersHorizontal size={16} />{m.createTableDialog_editCustomButton()}</button
					>
				{/if}
				<SwitchRow
					card
					label={m.createTableDialog_privateLabel()}
					checked={isPrivate}
					onChange={(checked) => (isPrivate = checked)}
				/>
			</div>
		{:else}
			<header class="custom-header">
				<button
					type="button"
					class="back"
					aria-label={m.createTableDialog_backToPresets()}
					data-testid="create-table-back"
					onclick={() => {
						view = 'presets';
						error = null;
					}}><ChevronLeft size={22} /></button
				>
				<PanelHeader title={m.createTableDialog_customTitle()} titleId="create-table-heading" />
			</header>

			<div class="scroll" bind:this={scrollEl}>
				<SegmentedControl
					legend={m.createTableDialog_startFromLegend()}
					name="custom_base"
					value={draft.base}
					options={RULESET_PRESET_OPTIONS.map((o) => ({ value: o.id, label: o.label() }))}
					onChange={loadPreset}
				/>

				<div class="summary" aria-live="polite">
					{#if undoable}
						<span>{m.createTableDialog_loadedPreset({ preset: presetLabel(undoable.preset) })}</span
						>
						<button type="button" class="link" onclick={undoReplace}
							>{m.createTableDialog_undoButton()}</button
						>
					{:else if changes > 0}
						<span
							>{m.createTableDialog_changesFrom({
								preset: presetLabel(draft.base),
								count: changes
							})}</span
						>
						<button
							type="button"
							class="link"
							data-testid="create-table-reset"
							onclick={() => loadPreset(draft.base)}>{m.createTableDialog_resetButton()}</button
						>
					{:else}
						<span>{m.createTableDialog_sameAsPreset({ preset: presetLabel(draft.base) })}</span>
					{/if}
				</div>

				<RulesEditor bind:rules={draft.rules} bind:overrides={draft.overrides} bind:activeTab />
			</div>
		{/if}

		{#if error}
			<p class="create-error" role="alert">{error}</p>
		{/if}

		<div class="create-actions">
			<button type="button" onclick={onCancel} disabled={submitting}
				>{m.createTableDialog_cancelButton()}</button
			>
			<button
				type="button"
				class="create-submit"
				data-testid="create-table-submit"
				onclick={handleSubmit}
				disabled={submitting}
			>
				{submitting ? m.createTableDialog_creatingButton() : m.createTableDialog_createButton()}
			</button>
		</div>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.create-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(90vw, 32rem);
		max-height: calc(100dvh - var(--space-6));
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.phone-landscape {
			gap: var(--space-2);
			padding: var(--space-3) var(--space-4) var(--space-2);
		}
	}

	// fixed height so switching rule tabs never resizes the dialog
	.create-dialog--custom {
		height: min(44rem, calc(100dvh - var(--space-6)));
	}

	.body {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		min-height: 0;
		overflow-y: auto;
	}

	.custom-header {
		display: flex;
		align-items: center;
		gap: var(--space-1);
		margin-inline-start: calc(-1 * var(--space-2));
	}

	.back {
		display: grid;
		place-items: center;
		flex: none;
		width: 40px;
		height: 40px;
		padding: 0;
		cursor: pointer;
		@include buttons.btn-ghost;
	}

	// start-from, summary and rule tabs scroll as one; the tab bar sticks (RulesEditor)
	.scroll {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin-inline: calc(-1 * var(--space-2));
		padding-inline: var(--space-2);
	}

	.edit-custom {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		min-height: 36px;
		padding: var(--space-1) var(--space-2);
		font: inherit;
		font-size: var(--font-size-sm);
		font-weight: 600;
		cursor: pointer;
		align-self: flex-start;
		@include buttons.btn-ghost;
	}

	.summary {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
		min-height: 1.5rem;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.link {
		padding: 0;
		border: none;
		background: none;
		color: var(--color-brass);
		font: inherit;
		font-weight: 600;
		text-decoration: underline;
		text-underline-offset: 2px;
		cursor: pointer;
	}

	.create-error {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-status-error);
	}

	.create-actions {
		display: flex;
		justify-content: flex-end;
		gap: var(--space-3);
		padding-top: var(--space-3);
		border-top: 1px solid var(--color-border);

		button {
			@include buttons.btn-base(var(--space-4));
			@include buttons.btn-secondary;
		}

		.create-submit {
			@include buttons.btn-primary;
		}
	}
</style>
