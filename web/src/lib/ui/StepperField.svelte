<script lang="ts">
	import Minus from '@lucide/svelte/icons/minus';
	import Plus from '@lucide/svelte/icons/plus';
	import { m } from '$lib/paraglide/messages.js';

	// integer input with -/+ buttons; `value` is null while the box is empty.
	let {
		label,
		description,
		value,
		min,
		unit,
		error,
		testid,
		onChange
	}: {
		label: string;
		description?: string;
		value: number | null;
		min: number;
		unit?: string;
		error?: string;
		testid?: string;
		onChange: (next: number | null) => void;
	} = $props();

	const uid = $props.id();
	const describedby = $derived(
		[description ? `${uid}-desc` : '', error ? `${uid}-error` : ''].filter(Boolean).join(' ') ||
			undefined
	);

	function step(delta: number): void {
		const base = typeof value === 'number' && Number.isFinite(value) ? Math.round(value) : min;
		onChange(Math.max(min, base + delta));
	}

	function handleInput(e: Event & { currentTarget: HTMLInputElement }): void {
		const raw = e.currentTarget.value;
		onChange(raw === '' ? null : Number(raw));
	}
</script>

<div class="stepper-field" class:stepper-field--error={!!error}>
	<div class="row">
		<span class="text">
			<label class="label" for="{uid}-input">{label}</label>
			{#if description}
				<span class="desc" id="{uid}-desc">{description}</span>
			{/if}
		</span>
		<span class="stepper">
			<button
				type="button"
				class="step"
				aria-label={m.stepper_decrease({ label })}
				disabled={typeof value === 'number' && value <= min}
				onclick={() => step(-1)}><Minus size={16} /></button
			>
			<input
				id="{uid}-input"
				type="number"
				inputmode="numeric"
				step="1"
				{min}
				value={value ?? ''}
				aria-invalid={error ? 'true' : undefined}
				aria-describedby={describedby}
				data-testid={testid}
				oninput={handleInput}
			/>
			{#if unit}<span class="unit" aria-hidden="true">{unit}</span>{/if}
			<button
				type="button"
				class="step"
				aria-label={m.stepper_increase({ label })}
				onclick={() => step(1)}><Plus size={16} /></button
			>
		</span>
	</div>
	{#if error}
		<p class="error" id="{uid}-error">{error}</p>
	{/if}
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.stepper-field {
		padding: var(--space-3) var(--space-1);
	}

	.stepper-field + :global(.stepper-field),
	:global(.switch-row) + .stepper-field,
	.stepper-field + :global(.switch-row) {
		border-top: 1px solid var(--color-border);
	}

	.row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
	}

	.text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.label {
		font-weight: 600;
	}

	.desc {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.stepper {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-1);
	}

	.step {
		display: grid;
		place-items: center;
		width: 36px;
		height: 36px;
		padding: 0;
		cursor: pointer;
		@include buttons.btn-ghost;

		&:disabled {
			cursor: not-allowed;
			opacity: 0.4;
		}
	}

	input {
		width: 3.5rem;
		min-height: 36px;
		padding: var(--space-1);
		font: inherit;
		font-variant-numeric: tabular-nums;
		text-align: center;
		color: var(--color-text);
		appearance: textfield;
		@include buttons.input-recessed;

		&::-webkit-inner-spin-button,
		&::-webkit-outer-spin-button {
			appearance: none;
			margin: 0;
		}
	}

	.stepper-field--error input {
		border-color: var(--color-status-error);
	}

	.unit {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.error {
		margin: var(--space-1) 0 0;
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}
</style>
