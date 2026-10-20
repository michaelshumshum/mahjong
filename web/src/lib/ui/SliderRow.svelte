<script lang="ts">
	let {
		label,
		description,
		value,
		min = 0,
		max = 100,
		step = 1,
		valueText,
		disabled = false,
		testid,
		onInput,
		onCommit
	}: {
		label: string;
		description?: string;
		value: number;
		min?: number;
		max?: number;
		step?: number;
		// shown beside the track and read out as aria-valuetext
		valueText: string;
		disabled?: boolean;
		testid?: string;
		onInput: (next: number) => void;
		// on release / each key step, not every drag tick
		onCommit?: (next: number) => void;
	} = $props();

	const uid = $props.id();
</script>

<label class="slider-row" class:slider-row--disabled={disabled}>
	<span class="slider-text">
		<span class="slider-label">{label}</span>
		{#if description}
			<span class="slider-desc" id="{uid}-desc">{description}</span>
		{/if}
	</span>
	<span class="slider-control">
		<input
			type="range"
			{min}
			{max}
			{step}
			{value}
			{disabled}
			data-testid={testid}
			aria-valuetext={valueText}
			aria-describedby={description ? `${uid}-desc` : undefined}
			oninput={(e) => onInput(e.currentTarget.valueAsNumber)}
			onchange={(e) => onCommit?.(e.currentTarget.valueAsNumber)}
		/>
		<span class="slider-value" aria-hidden="true">{valueText}</span>
	</span>
</label>

<style lang="scss">
	@use '$lib/styles/forms';

	.slider-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		min-height: 44px;
		padding: var(--space-3) var(--space-1);
	}

	:global(.switch-row) + .slider-row,
	.slider-row + :global(.switch-row) {
		border-top: 1px solid var(--color-border);
	}

	.slider-row--disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.slider-text {
		@include forms.field-text;
	}

	.slider-label {
		@include forms.field-label;
	}

	.slider-desc {
		@include forms.field-desc;
	}

	.slider-control {
		flex: none;
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	input {
		width: 8rem;
		margin: 0;
		accent-color: var(--color-brass);
		cursor: pointer;

		&:disabled {
			cursor: not-allowed;
		}
	}

	.slider-value {
		min-width: 4ch;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
		text-align: end;
	}
</style>
