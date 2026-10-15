<script module lang="ts">
	export type RulesTab = 'scoring' | 'hands' | 'play' | 'table';

	export interface OverrideRow {
		pattern: string;
		value: number | null;
	}
</script>

<script lang="ts">
	import { tick } from 'svelte';
	import X from '@lucide/svelte/icons/x';
	import Plus from '@lucide/svelte/icons/plus';
	import { m } from '$lib/paraglide/messages.js';
	import {
		FAAN_OVERRIDE_MAX,
		HAND_SET_OPTIONS,
		NUMERIC_RULE_MIN,
		VALID_FAAN_CAP,
		VALID_MIN_FAAN,
		isValidFaanOverride,
		isValidRuleNumber,
		type HandSet,
		type RuleSet
	} from '$lib/net/ruleset';
	import { OVERRIDABLE_PATTERNS } from './faan-guide';
	import { faanPatternLabel } from './faan-pattern-labels';
	import TabBar from './TabBar.svelte';
	import SegmentedControl from './SegmentedControl.svelte';
	import SwitchRow from './SwitchRow.svelte';
	import StepperField from './StepperField.svelte';

	let {
		rules = $bindable(),
		overrides = $bindable(),
		activeTab = $bindable('scoring')
	}: {
		rules: RuleSet;
		overrides: OverrideRow[];
		activeTab?: RulesTab;
	} = $props();

	const uid = $props.id();
	let overridesEl: HTMLElement | undefined = $state();

	const HAND_SET_DESC: Record<HandSet, () => string> = {
		CLASSIC: m.createTableDialog_handSetClassicDesc,
		NEW_6: m.createTableDialog_handSetNew6Desc,
		NEW_18: m.createTableDialog_handSetNew18Desc
	};

	// numeric fields per tab, for the error flag on each tab
	const TAB_NUMBERS: Record<RulesTab, (keyof typeof NUMERIC_RULE_MIN)[]> = {
		scoring: [],
		hands: [],
		play: ['wall_reserve'],
		table: [
			'turn_seconds',
			'claim_seconds',
			'hand_end_seconds',
			'turn_timeout_strikes',
			'disconnect_grace_seconds'
		]
	};

	function tabInvalid(tab: RulesTab): boolean {
		if (TAB_NUMBERS[tab].some((f) => !isValidRuleNumber(f, rules[f]))) return true;
		if (tab === 'hands') {
			return rules.hand_sets.length === 0 || overrides.some((r) => !isValidFaanOverride(r.value));
		}
		return false;
	}

	const tabs = $derived(
		(
			[
				{ id: 'scoring', label: m.createTableDialog_tabScoring() },
				{ id: 'hands', label: m.createTableDialog_tabHands() },
				{ id: 'play', label: m.createTableDialog_tabPlay() },
				{ id: 'table', label: m.createTableDialog_tabTable() }
			] as { id: RulesTab; label: string }[]
		).map((t) => ({
			...t,
			flag: tabInvalid(t.id) ? m.createTableDialog_tabNeedsFixing() : undefined
		}))
	);

	function numberError(field: keyof typeof NUMERIC_RULE_MIN): string | undefined {
		return isValidRuleNumber(field, rules[field])
			? undefined
			: m.createTableDialog_numberMinError({ min: NUMERIC_RULE_MIN[field] });
	}

	function toggleHandSet(value: HandSet, checked: boolean): void {
		rules.hand_sets = checked
			? HAND_SET_OPTIONS.map((o) => o.value).filter(
					(v) => v === value || rules.hand_sets.includes(v)
				)
			: rules.hand_sets.filter((v) => v !== value);
	}

	function tierLabel(tier: number | 'limit'): string {
		return tier === 'limit'
			? m.createTableDialog_overrideGroupLimit()
			: m.createTableDialog_overrideGroupFaan({ count: tier });
	}

	function defaultFaan(tier: number | 'limit'): number {
		return tier === 'limit' ? rules.faan_cap : tier;
	}

	// patterns scored under the current hand sets, grouped by default tier, minus ones already
	// overridden by another row
	function patternGroups(current: string | null): { tier: number | 'limit'; patterns: string[] }[] {
		const taken = new Set(overrides.map((r) => r.pattern));
		const groups = new Map<number | 'limit', string[]>();
		for (const p of OVERRIDABLE_PATTERNS) {
			if (p.pattern !== current && (taken.has(p.pattern) || !rules.hand_sets.includes(p.handSet)))
				continue;
			if (p.pattern === '雞糊' && rules.min_faan > 0 && p.pattern !== current) continue;
			groups.set(p.tier, [...(groups.get(p.tier) ?? []), p.pattern]);
		}
		return [...groups].map(([tier, patterns]) => ({ tier, patterns }));
	}

	const addable = $derived(patternGroups(null).flatMap((g) => g.patterns));

	async function addOverride(): Promise<void> {
		const pattern = addable[0];
		if (!pattern) return;
		const tier = OVERRIDABLE_PATTERNS.find((p) => p.pattern === pattern)?.tier ?? 1;
		overrides = [...overrides, { pattern, value: defaultFaan(tier) }];
		await tick();
		const selects = overridesEl?.querySelectorAll<HTMLSelectElement>('select');
		selects?.[selects.length - 1]?.focus();
	}

	function setOverrideValue(index: number, raw: string): void {
		overrides[index].value = raw === '' ? null : Number(raw);
	}
</script>

<div class="rules-editor">
	<div class="tabbar">
		<TabBar
			{tabs}
			active={activeTab}
			idPrefix={uid}
			label={m.createTableDialog_tabsAriaLabel()}
			testidPrefix="rules-tab"
			onChange={(tab) => (activeTab = tab)}
		/>
	</div>

	<div class="panels">
		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-scoring"
			aria-labelledby="{uid}-tab-scoring"
			hidden={activeTab !== 'scoring'}
		>
			<SegmentedControl
				legend={m.createTableDialog_minFaanLabel()}
				name="min_faan"
				value={String(rules.min_faan)}
				options={VALID_MIN_FAAN.map((n) => ({
					value: String(n),
					label: String(n),
					description:
						n === 0
							? m.createTableDialog_minFaanZeroDesc()
							: m.createTableDialog_minFaanDesc({ count: n })
				}))}
				onChange={(v) => (rules.min_faan = Number(v))}
			/>
			<SegmentedControl
				legend={m.createTableDialog_faanCapLabel()}
				name="faan_cap"
				value={String(rules.faan_cap)}
				options={VALID_FAAN_CAP.map((n) => ({
					value: String(n),
					label: String(n),
					description: m.createTableDialog_faanCapDesc({ count: n })
				}))}
				onChange={(v) => (rules.faan_cap = Number(v))}
			/>
			<SegmentedControl
				legend={m.createTableDialog_scoreTableLabel()}
				name="score_table"
				value={rules.score_table}
				options={[
					{
						value: 'half_spicy',
						label: m.createTableDialog_scoreTableHalfSpicy(),
						description: m.createTableDialog_scoreTableHalfSpicyDesc()
					},
					{
						value: 'full_spicy',
						label: m.createTableDialog_scoreTableFullSpicy(),
						description: m.createTableDialog_scoreTableFullSpicyDesc()
					}
				]}
				onChange={(v) => (rules.score_table = v)}
			/>
			<SegmentedControl
				legend={m.createTableDialog_discardPaymentLabel()}
				name="discard_payment"
				value={rules.discard_payment}
				options={[
					{
						value: 'all',
						label: m.createTableDialog_discardPaymentAll(),
						description: m.createTableDialog_discardPaymentAllDesc()
					},
					{
						value: 'half',
						label: m.createTableDialog_discardPaymentHalf(),
						description: m.createTableDialog_discardPaymentHalfDesc()
					}
				]}
				onChange={(v) => (rules.discard_payment = v)}
			/>
		</div>

		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-hands"
			aria-labelledby="{uid}-tab-hands"
			hidden={activeTab !== 'hands'}
		>
			<fieldset class="group">
				<legend>{m.createTableDialog_handSetsLabel()}</legend>
				<div class="card">
					{#each HAND_SET_OPTIONS as option (option.value)}
						<SwitchRow
							label={option.label()}
							description={HAND_SET_DESC[option.value]()}
							checked={rules.hand_sets.includes(option.value)}
							onChange={(checked) => toggleHandSet(option.value, checked)}
						/>
					{/each}
				</div>
				{#if rules.hand_sets.length === 0}
					<p class="error" role="alert">{m.createTableDialog_handSetsRequired()}</p>
				{/if}
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_flowersLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.createTableDialog_flowersEnabledLabel()}
						description={m.createTableDialog_flowersEnabledDesc()}
						checked={rules.flowers_enabled}
						onChange={(checked) => (rules.flowers_enabled = checked)}
					/>
					<SwitchRow
						label={m.createTableDialog_flowersScoreLabel()}
						description={m.createTableDialog_flowersScoreDesc()}
						checked={rules.flowers_score}
						disabled={!rules.flowers_enabled}
						onChange={(checked) => (rules.flowers_score = checked)}
					/>
					<SwitchRow
						label={m.createTableDialog_sevenFlowersInstantWinLabel()}
						description={m.createTableDialog_sevenFlowersInstantWinDesc()}
						checked={rules.seven_flowers_instant_win}
						disabled={!rules.flowers_enabled}
						onChange={(checked) => (rules.seven_flowers_instant_win = checked)}
					/>
					<SwitchRow
						label={m.createTableDialog_eightFlowersInstantWinLabel()}
						description={m.createTableDialog_eightFlowersInstantWinDesc()}
						checked={rules.eight_flowers_instant_win}
						disabled={!rules.flowers_enabled}
						onChange={(checked) => (rules.eight_flowers_instant_win = checked)}
					/>
				</div>
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_faanOverridesLabel()}</legend>
				<p class="hint">{m.createTableDialog_faanOverridesDesc()}</p>
				{#if overrides.length > 0}
					<div class="card overrides" bind:this={overridesEl}>
						{#each overrides as row, i (i)}
							{@const invalid = !isValidFaanOverride(row.value)}
							<div class="override-row">
								<select
									aria-label={m.createTableDialog_overridePatternAriaLabel()}
									bind:value={row.pattern}
									data-testid="override-pattern"
								>
									{#each patternGroups(row.pattern) as group (group.tier)}
										<optgroup label={tierLabel(group.tier)}>
											{#each group.patterns as pattern (pattern)}
												<option value={pattern}>{faanPatternLabel(pattern)}</option>
											{/each}
										</optgroup>
									{/each}
								</select>
								<input
									type="number"
									inputmode="numeric"
									min="0"
									max={FAAN_OVERRIDE_MAX}
									step="1"
									aria-label={m.createTableDialog_overrideFaanValueAriaLabel()}
									aria-invalid={invalid ? 'true' : undefined}
									value={row.value ?? ''}
									oninput={(e) => setOverrideValue(i, e.currentTarget.value)}
									data-testid="override-value"
								/>
								<button
									type="button"
									class="icon-btn"
									aria-label={m.createTableDialog_removeOverrideAriaLabel({
										pattern: faanPatternLabel(row.pattern)
									})}
									onclick={() => (overrides = overrides.filter((_, j) => j !== i))}
									><X size={16} /></button
								>
							</div>
							{#if invalid}
								<p class="error">
									{m.createTableDialog_overrideInvalid({ max: FAAN_OVERRIDE_MAX })}
								</p>
							{/if}
						{/each}
					</div>
				{/if}
				<button
					type="button"
					class="add-override"
					disabled={addable.length === 0}
					onclick={addOverride}><Plus size={16} />{m.createTableDialog_addOverrideButton()}</button
				>
			</fieldset>
		</div>

		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-play"
			aria-labelledby="{uid}-tab-play"
			hidden={activeTab !== 'play'}
		>
			<SegmentedControl
				legend={m.createTableDialog_gameLengthLabel()}
				name="game_length"
				value={rules.game_length}
				options={[
					{
						value: 'EAST_ONLY',
						label: m.createTableDialog_gameLengthEastOnly(),
						description: m.createTableDialog_gameLengthEastOnlyDesc()
					},
					{
						value: 'EAST_SOUTH',
						label: m.createTableDialog_gameLengthEastSouth(),
						description: m.createTableDialog_gameLengthEastSouthDesc()
					},
					{
						value: 'FULL',
						label: m.createTableDialog_gameLengthFull(),
						description: m.createTableDialog_gameLengthFullDesc()
					}
				]}
				onChange={(v) => (rules.game_length = v)}
			/>

			<fieldset class="group">
				<legend>{m.createTableDialog_dealerLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.createTableDialog_dealerRepeatOnWinLabel()}
						description={m.createTableDialog_dealerRepeatOnWinDesc()}
						checked={rules.dealer_repeat_on_win}
						onChange={(checked) => (rules.dealer_repeat_on_win = checked)}
					/>
					<SwitchRow
						label={m.createTableDialog_dealerRepeatOnDrawLabel()}
						description={m.createTableDialog_dealerRepeatOnDrawDesc()}
						checked={rules.dealer_repeat_on_draw}
						onChange={(checked) => (rules.dealer_repeat_on_draw = checked)}
					/>
				</div>
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_kongsLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.createTableDialog_kongRobEnabledLabel()}
						description={m.createTableDialog_kongRobEnabledDesc()}
						checked={rules.kong_rob_enabled}
						onChange={(checked) => (rules.kong_rob_enabled = checked)}
					/>
					<SwitchRow
						label={m.createTableDialog_concealedKongRobbableLabel()}
						description={m.createTableDialog_concealedKongRobbableDesc()}
						checked={rules.concealed_kong_robbable}
						disabled={!rules.kong_rob_enabled}
						onChange={(checked) => (rules.concealed_kong_robbable = checked)}
					/>
				</div>
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_wallLegend()}</legend>
				<div class="card">
					<StepperField
						label={m.createTableDialog_wallReserveLabel()}
						description={m.createTableDialog_wallReserveDesc()}
						value={rules.wall_reserve}
						min={NUMERIC_RULE_MIN.wall_reserve}
						unit={m.createTableDialog_tilesUnit()}
						error={numberError('wall_reserve')}
						testid="rule-wall_reserve"
						onChange={(v) => (rules.wall_reserve = v as number)}
					/>
				</div>
			</fieldset>
		</div>

		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-table"
			aria-labelledby="{uid}-tab-table"
			hidden={activeTab !== 'table'}
		>
			<fieldset class="group">
				<legend>{m.createTableDialog_timeLimitsLegend()}</legend>
				<div class="card">
					<StepperField
						label={m.createTableDialog_turnSecondsLabel()}
						description={m.createTableDialog_turnSecondsDesc()}
						value={rules.turn_seconds}
						min={NUMERIC_RULE_MIN.turn_seconds}
						unit={m.createTableDialog_secondsUnit()}
						error={numberError('turn_seconds')}
						testid="rule-turn_seconds"
						onChange={(v) => (rules.turn_seconds = v as number)}
					/>
					<StepperField
						label={m.createTableDialog_claimSecondsLabel()}
						description={m.createTableDialog_claimSecondsDesc()}
						value={rules.claim_seconds}
						min={NUMERIC_RULE_MIN.claim_seconds}
						unit={m.createTableDialog_secondsUnit()}
						error={numberError('claim_seconds')}
						testid="rule-claim_seconds"
						onChange={(v) => (rules.claim_seconds = v as number)}
					/>
					<StepperField
						label={m.createTableDialog_handEndSecondsLabel()}
						description={m.createTableDialog_handEndSecondsDesc()}
						value={rules.hand_end_seconds}
						min={NUMERIC_RULE_MIN.hand_end_seconds}
						unit={m.createTableDialog_secondsUnit()}
						error={numberError('hand_end_seconds')}
						testid="rule-hand_end_seconds"
						onChange={(v) => (rules.hand_end_seconds = v as number)}
					/>
				</div>
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_botTakeoverLegend()}</legend>
				<div class="card">
					<StepperField
						label={m.createTableDialog_turnTimeoutStrikesLabel()}
						description={m.createTableDialog_turnTimeoutStrikesDesc()}
						value={rules.turn_timeout_strikes}
						min={NUMERIC_RULE_MIN.turn_timeout_strikes}
						error={numberError('turn_timeout_strikes')}
						testid="rule-turn_timeout_strikes"
						onChange={(v) => (rules.turn_timeout_strikes = v as number)}
					/>
					<StepperField
						label={m.createTableDialog_disconnectGraceSecondsLabel()}
						description={m.createTableDialog_disconnectGraceSecondsDesc()}
						value={rules.disconnect_grace_seconds}
						min={NUMERIC_RULE_MIN.disconnect_grace_seconds}
						unit={m.createTableDialog_secondsUnit()}
						error={numberError('disconnect_grace_seconds')}
						testid="rule-disconnect_grace_seconds"
						onChange={(v) => (rules.disconnect_grace_seconds = v as number)}
					/>
				</div>
			</fieldset>

			<fieldset class="group">
				<legend>{m.createTableDialog_fairnessLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.createTableDialog_provableFairnessLabel()}
						description={m.createTableDialog_provableFairnessDesc()}
						checked={rules.provable_fairness}
						onChange={(checked) => (rules.provable_fairness = checked)}
					/>
				</div>
			</fieldset>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';

	.rules-editor {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	// sticks inside the owner's scroll container
	.tabbar {
		position: sticky;
		top: 0;
		z-index: 1;
		background: var(--color-surface-raised);
	}

	.panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		padding-block: var(--space-1) var(--space-2);

		&[hidden] {
			display: none;
		}
	}

	.group {
		@include forms.form-group;
		gap: var(--space-2);
	}

	legend {
		@include forms.settings-legend;
	}

	.card {
		@include forms.settings-card;
	}

	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.error {
		margin: 0;
		padding-bottom: var(--space-2);
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}

	.overrides {
		padding-block: var(--space-2);
	}

	.override-row {
		display: flex;
		gap: var(--space-2);
		align-items: center;
		padding-block: var(--space-1);

		select,
		input {
			min-height: 36px;
			padding: var(--space-1) var(--space-2);
			font: inherit;
			font-size: var(--font-size-sm);
			color: var(--color-text);
			@include buttons.input-recessed;
		}

		select {
			flex: 1 1 auto;
			min-width: 0;
		}

		input {
			width: 3.5rem;
			text-align: center;
			font-variant-numeric: tabular-nums;

			&[aria-invalid='true'] {
				border-color: var(--color-status-error);
			}
		}
	}

	.icon-btn {
		display: grid;
		place-items: center;
		flex: none;
		width: 36px;
		height: 36px;
		padding: 0;
		cursor: pointer;
		@include buttons.btn-ghost;
	}

	.add-override {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		align-self: flex-start;
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-ghost;

		&:disabled {
			cursor: not-allowed;
			opacity: 0.5;
		}
	}
</style>
