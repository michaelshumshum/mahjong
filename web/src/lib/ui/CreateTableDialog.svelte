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
		<h2 id="create-table-heading">Create a table</h2>

		<fieldset class="preset-group">
			<legend>Rules</legend>
			{#each RULESET_PRESET_OPTIONS as option (option.id)}
				<label class="preset-option">
					<input type="radio" name="preset" value={option.id} bind:group={presetId} />
					<span class="preset-label">{option.label}</span>
					<span class="preset-description">{option.description}</span>
				</label>
			{/each}
			<label class="preset-option">
				<input type="radio" name="preset" value={CUSTOM_PRESET_ID} bind:group={presetId} />
				<span class="preset-label">Custom</span>
				<span class="preset-description">choose every rule yourself</span>
			</label>
		</fieldset>

		{#if presetId === CUSTOM_PRESET_ID}
			<div class="custom-form">
				<fieldset class="group">
					<legend>Scoring</legend>
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
								<label class="toggle">
									<input
										type="checkbox"
										checked={custom.hand_sets.includes(option.value)}
										onchange={(e) => toggleHandSet(option.value, e.currentTarget.checked)}
									/>
									{option.label}
								</label>
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
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.flowers_score} />
						Seat flowers score
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.seven_flowers_instant_win} />
						Seven flowers instant win
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.eight_flowers_instant_win} />
						Eight flowers instant win
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.thirteen_orphans_wait_bonus} />
						Thirteen orphans wait bonus
					</label>

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
				</fieldset>

				<fieldset class="group">
					<legend>Flow</legend>
					<label class="field">
						Game length
						<select bind:value={custom.game_length}>
							<option value="EAST_ONLY">East only</option>
							<option value="EAST_SOUTH">East + South</option>
							<option value="FULL">Full (four rounds)</option>
						</select>
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.dealer_repeat_on_win} />
						Dealer repeats on win
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.dealer_repeat_on_draw} />
						Dealer repeats on draw
					</label>
					<label class="field">
						Wall reserve
						<input type="number" min="0" step="1" bind:value={custom.wall_reserve} />
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.four_kong_abort} />
						Four kong abort
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.nine_terminals_abort} />
						Nine terminals abort
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.tenpai_payments} />
						Tenpai payments on draw
					</label>
				</fieldset>

				<fieldset class="group">
					<legend>Variants</legend>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.flowers_enabled} />
						Flowers enabled
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.kong_rob_enabled} />
						Robbing the kong
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.concealed_kong_robbable} />
						Concealed kong robbable
					</label>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.pao_rules} />
						Pao (liability) rules
					</label>
				</fieldset>

				<fieldset class="group">
					<legend>Fairness</legend>
					<label class="toggle">
						<input type="checkbox" bind:checked={custom.provable_fairness} />
						Provable fairness (seed commitment)
					</label>
				</fieldset>

				<fieldset class="group">
					<legend>Timing</legend>
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
				</fieldset>
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
		position: fixed;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.5);
		z-index: var(--z-modal);
		padding: var(--space-3);
	}

	.create-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: 100%;
		max-width: 32rem;
		max-height: 90vh;
		overflow-y: auto;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}
	}

	fieldset {
		border: none;
		padding: 0;
		margin: 0;
	}

	legend {
		padding: 0 0 var(--space-2);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.preset-group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.preset-option {
		display: grid;
		grid-template-columns: auto 1fr;
		column-gap: var(--space-2);
		align-items: baseline;
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		cursor: pointer;

		&:hover {
			background: rgb(255 255 255 / 0.06);
		}
	}

	.preset-label {
		font-weight: 600;
	}

	.preset-description {
		grid-column: 2;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.custom-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		padding-top: var(--space-2);
		border-top: 1px solid var(--color-border);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.field {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
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
		gap: var(--space-3);
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 36px;
		font-size: var(--font-size-sm);
		cursor: pointer;
	}

	.toggle input {
		accent-color: var(--color-accent);
		width: 1.05em;
		height: 1.05em;
		cursor: pointer;
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
			min-height: 44px;
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
