<script lang="ts">
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
			error = "Couldn't create the table — try again.";
			submitting = false;
		}
	}
</script>

<div class="panel-overlay">
	<div class="create-dialog" role="dialog" aria-modal="true" aria-labelledby="create-table-heading">
		<PanelHeader title="Create a table" titleId="create-table-heading" />

		<FormGroup legend="Rules">
			{#each RULESET_PRESET_OPTIONS as option (option.id)}
				<OptionRow
					type="radio"
					name="preset"
					value={option.id}
					label={option.label}
					checked={presetId === option.id}
					onChange={() => (presetId = option.id)}
				/>
			{/each}
			<OptionRow
				type="radio"
				name="preset"
				value={CUSTOM_PRESET_ID}
				label="Custom"
				checked={presetId === CUSTOM_PRESET_ID}
				onChange={() => (presetId = CUSTOM_PRESET_ID)}
			/>
		</FormGroup>

		{#if presetId === CUSTOM_PRESET_ID}
			<div class="custom-form">
				<FormGroup legend="Scoring">
					<label class="field">
						Minimum faan
						<select bind:value={custom.min_faan}>
							{#each VALID_MIN_FAAN as value (value)}
								<option {value}>{value}</option>
							{/each}
						</select>
					</label>
					<label class="field">
						Faan cap
						<select bind:value={custom.faan_cap}>
							{#each VALID_FAAN_CAP as value (value)}
								<option {value}>{value}</option>
							{/each}
						</select>
					</label>
					<label class="field">
						Score table
						<select bind:value={custom.score_table}>
							<option value="half_spicy">Half spicy</option>
							<option value="full_spicy">Full spicy</option>
						</select>
					</label>
					<div class="field">
						Hand sets
						<div class="checkbox-row">
							{#each HAND_SET_OPTIONS as option (option.value)}
								<OptionRow
									type="checkbox"
									label={option.label}
									checked={custom.hand_sets.includes(option.value)}
									onChange={(checked) => toggleHandSet(option.value, checked)}
								/>
							{/each}
						</div>
					</div>
					<label class="field">
						Discard payment
						<select bind:value={custom.discard_payment}>
							<option value="all">Discarder pays all</option>
							<option value="half">Discarder pays half</option>
						</select>
					</label>
					<label class="field">
						Self-draw multiplier
						<input type="number" step="0.1" min="1" bind:value={custom.self_draw_multiplier} />
					</label>
					<OptionRow
						type="checkbox"
						label="Seat flowers score"
						checked={custom.flowers_score}
						onChange={(checked) => (custom.flowers_score = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Seven flowers instant win"
						checked={custom.seven_flowers_instant_win}
						onChange={(checked) => (custom.seven_flowers_instant_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Eight flowers instant win"
						checked={custom.eight_flowers_instant_win}
						onChange={(checked) => (custom.eight_flowers_instant_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Thirteen orphans wait bonus"
						checked={custom.thirteen_orphans_wait_bonus}
						onChange={(checked) => (custom.thirteen_orphans_wait_bonus = checked)}
					/>

					<div class="field">
						Faan overrides
						{#each overrideRows as row, i (i)}
							<div class="override-row">
								<input
									type="text"
									placeholder="pattern name"
									aria-label="override pattern name"
									bind:value={row.key}
								/>
								<input type="number" aria-label="override faan value" bind:value={row.value} />
								<button type="button" onclick={() => removeOverrideRow(i)}>Remove</button>
							</div>
						{/each}
						<button type="button" class="add-override" onclick={addOverrideRow}>Add override</button
						>
					</div>
				</FormGroup>

				<FormGroup legend="Flow">
					<label class="field">
						Game length
						<select bind:value={custom.game_length}>
							<option value="EAST_ONLY">East only</option>
							<option value="EAST_SOUTH">East + South</option>
							<option value="FULL">Full (four rounds)</option>
						</select>
					</label>
					<OptionRow
						type="checkbox"
						label="Dealer repeats on win"
						checked={custom.dealer_repeat_on_win}
						onChange={(checked) => (custom.dealer_repeat_on_win = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Dealer repeats on draw"
						checked={custom.dealer_repeat_on_draw}
						onChange={(checked) => (custom.dealer_repeat_on_draw = checked)}
					/>
					<label class="field">
						Wall reserve
						<input type="number" min="0" step="1" bind:value={custom.wall_reserve} />
					</label>
					<OptionRow
						type="checkbox"
						label="Four kong abort"
						checked={custom.four_kong_abort}
						onChange={(checked) => (custom.four_kong_abort = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Nine terminals abort"
						checked={custom.nine_terminals_abort}
						onChange={(checked) => (custom.nine_terminals_abort = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Tenpai payments on draw"
						checked={custom.tenpai_payments}
						onChange={(checked) => (custom.tenpai_payments = checked)}
					/>
				</FormGroup>

				<FormGroup legend="Variants">
					<OptionRow
						type="checkbox"
						label="Flowers enabled"
						checked={custom.flowers_enabled}
						onChange={(checked) => (custom.flowers_enabled = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Robbing the kong"
						checked={custom.kong_rob_enabled}
						onChange={(checked) => (custom.kong_rob_enabled = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Concealed kong robbable"
						checked={custom.concealed_kong_robbable}
						onChange={(checked) => (custom.concealed_kong_robbable = checked)}
					/>
					<OptionRow
						type="checkbox"
						label="Pao (liability) rules"
						checked={custom.pao_rules}
						onChange={(checked) => (custom.pao_rules = checked)}
					/>
				</FormGroup>

				<FormGroup legend="Fairness">
					<OptionRow
						type="checkbox"
						label="Provable fairness (seed commitment)"
						checked={custom.provable_fairness}
						onChange={(checked) => (custom.provable_fairness = checked)}
					/>
				</FormGroup>

				<FormGroup legend="Timing">
					<label class="field">
						Turn seconds
						<input type="number" min="1" step="1" bind:value={custom.turn_seconds} />
					</label>
					<label class="field">
						Claim window seconds
						<input type="number" min="1" step="1" bind:value={custom.claim_seconds} />
					</label>
					<label class="field">
						Hand-end hold seconds
						<input type="number" min="0" step="1" bind:value={custom.hand_end_seconds} />
					</label>
					<label class="field">
						Turn timeout strikes
						<input type="number" min="1" step="1" bind:value={custom.turn_timeout_strikes} />
					</label>
					<label class="field">
						Disconnect grace seconds
						<input type="number" min="0" step="1" bind:value={custom.disconnect_grace_seconds} />
					</label>
				</FormGroup>
			</div>
		{/if}

		{#if error}
			<p class="create-error">{error}</p>
		{/if}

		<div class="create-actions">
			<button type="button" onclick={onCancel} disabled={submitting}>Cancel</button>
			<button type="button" class="create-submit" onclick={handleSubmit} disabled={submitting}>
				{submitting ? 'Creating…' : 'Create'}
			</button>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

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
