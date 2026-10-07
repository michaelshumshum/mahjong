<script lang="ts">
	import ModalDialog from './ModalDialog.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { createTable, type CreateTableRequest } from '$lib/net/lobby';
	import {
		CUSTOM_PRESET_ID,
		DEFAULT_PRESET_ID,
		DEFAULT_RULESET,
		HAND_SET_OPTIONS,
		RULESET_PRESET_OPTIONS,
		VALID_FAAN_CAP,
		VALID_MIN_FAAN,
		type HandSet,
		type RuleSet
	} from '$lib/net/ruleset';
	import PanelHeader from './PanelHeader.svelte';
	import FormGroup from './FormGroup.svelte';
	import OptionRow from './OptionRow.svelte';

	let { onCreated, onCancel }: { onCreated: (tableId: string) => void; onCancel: () => void } =
		$props();

	let presetId = $state(DEFAULT_PRESET_ID);
	// prefilled from the same defaults `hk_classic` resolves to server-side -- editing from a
	// sensible starting point, not a blank/zeroed form.
	let custom = $state<RuleSet>({ ...DEFAULT_RULESET, faan_overrides: {} });
	let overrideRows = $state<{ key: string; value: number }[]>([]);
	let submitting = $state(false);
	let error = $state<string | null>(null);

	function toggleHandSet(value: HandSet, checked: boolean): void {
		custom.hand_sets = checked
			? [...custom.hand_sets, value]
			: custom.hand_sets.filter((v) => v !== value);
	}

	function addOverrideRow(): void {
		overrideRows = [...overrideRows, { key: '', value: 0 }];
	}

	function removeOverrideRow(index: number): void {
		overrideRows = overrideRows.filter((_, i) => i !== index);
	}

	async function handleSubmit(): Promise<void> {
		submitting = true;
		error = null;
		const body: CreateTableRequest =
			presetId === CUSTOM_PRESET_ID
				? {
						ruleset: CUSTOM_PRESET_ID,
						rules: {
							...custom,
							// never user-editable -- see ruleset.ts's RuleSet doc on why exposing this
							// would silently discard the whole custom ruleset the instant it's toggled on
							multi_win: false,
							faan_overrides: Object.fromEntries(
								overrideRows
									.filter((row) => row.key.trim() !== '')
									.map((row) => [row.key.trim(), row.value])
							)
						}
					}
				: { ruleset: presetId };
		try {
			const response = await createTable(body);
			onCreated(response.table_id);
		} catch {
			error = m.createTableDialog_createError();
			submitting = false;
		}
	}
</script>

<ModalDialog labelledby="create-table-heading" onCancel={() => !submitting && onCancel()}>
	<div class="create-dialog" data-testid="create-table-dialog">
		<PanelHeader title={m.createTableDialog_title()} titleId="create-table-heading" />

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
				description={m.createTableDialog_customDescription()}
				checked={presetId === CUSTOM_PRESET_ID}
				onChange={() => (presetId = CUSTOM_PRESET_ID)}
			/>
		</FormGroup>

		{#if presetId === CUSTOM_PRESET_ID}
			<div class="custom-form">
				<FormGroup legend={m.createTableDialog_scoringLegend()}>
					<label class="field">
						{m.createTableDialog_minFaanLabel()}
						<select bind:value={custom.min_faan}>
							{#each VALID_MIN_FAAN as value (value)}
								<option {value}>{value}</option>
							{/each}
						</select>
					</label>
					<label class="field">
						{m.createTableDialog_faanCapLabel()}
						<select bind:value={custom.faan_cap}>
							{#each VALID_FAAN_CAP as value (value)}
								<option {value}>{value}</option>
							{/each}
						</select>
					</label>
					<label class="field">
						{m.createTableDialog_scoreTableLabel()}
						<select bind:value={custom.score_table}>
							<option value="half_spicy">{m.createTableDialog_scoreTableHalfSpicy()}</option>
							<option value="full_spicy">{m.createTableDialog_scoreTableFullSpicy()}</option>
						</select>
					</label>
					<div class="field">
						{m.createTableDialog_handSetsLabel()}
						<div class="checkbox-row">
							{#each HAND_SET_OPTIONS as option (option.value)}
								<OptionRow
									type="checkbox"
									label={option.label()}
									checked={custom.hand_sets.includes(option.value)}
									onChange={(checked) => toggleHandSet(option.value, checked)}
								/>
							{/each}
						</div>
					</div>
					<label class="field">
						{m.createTableDialog_discardPaymentLabel()}
						<select bind:value={custom.discard_payment}>
							<option value="all">{m.createTableDialog_discardPaymentAll()}</option>
							<option value="half">{m.createTableDialog_discardPaymentHalf()}</option>
						</select>
					</label>
					<label class="field">
						{m.createTableDialog_selfDrawMultiplierLabel()}
						<input type="number" step="0.1" min="1" bind:value={custom.self_draw_multiplier} />
					</label>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_flowersScoreLabel()}
						checked={custom.flowers_score}
						onChange={(checked) => (custom.flowers_score = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_sevenFlowersInstantWinLabel()}
						checked={custom.seven_flowers_instant_win}
						onChange={(checked) => (custom.seven_flowers_instant_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_eightFlowersInstantWinLabel()}
						checked={custom.eight_flowers_instant_win}
						onChange={(checked) => (custom.eight_flowers_instant_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_thirteenOrphansWaitBonusLabel()}
						checked={custom.thirteen_orphans_wait_bonus}
						onChange={(checked) => (custom.thirteen_orphans_wait_bonus = checked)}
					/>

					<div class="field">
						{m.createTableDialog_faanOverridesLabel()}
						{#each overrideRows as row, i (i)}
							<div class="override-row">
								<input
									type="text"
									placeholder={m.createTableDialog_overridePatternPlaceholder()}
									aria-label={m.createTableDialog_overridePatternAriaLabel()}
									bind:value={row.key}
								/>
								<input
									type="number"
									aria-label={m.createTableDialog_overrideFaanValueAriaLabel()}
									bind:value={row.value}
								/>
								<button type="button" onclick={() => removeOverrideRow(i)}
									>{m.createTableDialog_removeOverrideButton()}</button
								>
							</div>
						{/each}
						<button type="button" class="add-override" onclick={addOverrideRow}
							>{m.createTableDialog_addOverrideButton()}</button
						>
					</div>
				</FormGroup>

				<FormGroup legend={m.createTableDialog_flowLegend()}>
					<label class="field">
						{m.createTableDialog_gameLengthLabel()}
						<select bind:value={custom.game_length}>
							<option value="EAST_ONLY">{m.createTableDialog_gameLengthEastOnly()}</option>
							<option value="EAST_SOUTH">{m.createTableDialog_gameLengthEastSouth()}</option>
							<option value="FULL">{m.createTableDialog_gameLengthFull()}</option>
						</select>
					</label>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_dealerRepeatOnWinLabel()}
						checked={custom.dealer_repeat_on_win}
						onChange={(checked) => (custom.dealer_repeat_on_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_dealerRepeatOnDrawLabel()}
						checked={custom.dealer_repeat_on_draw}
						onChange={(checked) => (custom.dealer_repeat_on_draw = checked)}
					/>
					<label class="field">
						{m.createTableDialog_wallReserveLabel()}
						<input type="number" min="0" step="1" bind:value={custom.wall_reserve} />
					</label>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_fourKongAbortLabel()}
						checked={custom.four_kong_abort}
						onChange={(checked) => (custom.four_kong_abort = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_nineTerminalsAbortLabel()}
						checked={custom.nine_terminals_abort}
						onChange={(checked) => (custom.nine_terminals_abort = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_tenpaiPaymentsLabel()}
						checked={custom.tenpai_payments}
						onChange={(checked) => (custom.tenpai_payments = checked)}
					/>
				</FormGroup>

				<FormGroup legend={m.createTableDialog_variantsLegend()}>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_flowersEnabledLabel()}
						checked={custom.flowers_enabled}
						onChange={(checked) => (custom.flowers_enabled = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_kongRobEnabledLabel()}
						checked={custom.kong_rob_enabled}
						onChange={(checked) => (custom.kong_rob_enabled = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_concealedKongRobbableLabel()}
						checked={custom.concealed_kong_robbable}
						onChange={(checked) => (custom.concealed_kong_robbable = checked)}
					/>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_paoRulesLabel()}
						checked={custom.pao_rules}
						onChange={(checked) => (custom.pao_rules = checked)}
					/>
				</FormGroup>

				<FormGroup legend={m.createTableDialog_fairnessLegend()}>
					<OptionRow
						type="checkbox"
						label={m.createTableDialog_provableFairnessLabel()}
						checked={custom.provable_fairness}
						onChange={(checked) => (custom.provable_fairness = checked)}
					/>
				</FormGroup>

				<FormGroup legend={m.createTableDialog_timingLegend()}>
					<label class="field">
						{m.createTableDialog_turnSecondsLabel()}
						<input type="number" min="1" step="1" bind:value={custom.turn_seconds} />
					</label>
					<label class="field">
						{m.createTableDialog_claimSecondsLabel()}
						<input type="number" min="1" step="1" bind:value={custom.claim_seconds} />
					</label>
					<label class="field">
						{m.createTableDialog_handEndSecondsLabel()}
						<input type="number" min="0" step="1" bind:value={custom.hand_end_seconds} />
					</label>
					<label class="field">
						{m.createTableDialog_turnTimeoutStrikesLabel()}
						<input type="number" min="1" step="1" bind:value={custom.turn_timeout_strikes} />
					</label>
					<label class="field">
						{m.createTableDialog_disconnectGraceSecondsLabel()}
						<input type="number" min="0" step="1" bind:value={custom.disconnect_grace_seconds} />
					</label>
				</FormGroup>
			</div>
		{/if}

		{#if error}
			<p class="create-error">{error}</p>
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

	.create-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: 100%;
		max-width: 32rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	.custom-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		padding-top: var(--space-2);
		border-top: 1px solid var(--color-border);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.field select,
	.field input[type='number'],
	.field input[type='text'] {
		font: inherit;
		min-height: 36px;
		padding: var(--space-1) var(--space-2);
		color: var(--color-text);
		@include buttons.input-recessed;
	}

	.checkbox-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.override-row {
		display: flex;
		gap: var(--space-2);
		align-items: center;

		input[type='text'] {
			flex: 2;
		}

		input[type='number'] {
			flex: 1;
			min-width: 4rem;
		}
	}

	.add-override {
		align-self: flex-start;
		font: inherit;
		font-size: var(--font-size-sm);
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		cursor: pointer;
		@include buttons.btn-ghost;
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

		button {
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-4);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-secondary;
		}

		.create-submit {
			@include buttons.btn-primary;
		}
	}
</style>
