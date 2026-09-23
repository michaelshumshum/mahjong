<script lang="ts">
	let {
		type,
		name,
		value,
		checked,
		label,
		onChange
	}: {
		type: 'checkbox' | 'radio';
		name?: string;
		value?: string;
		checked: boolean;
		label: string;
		onChange: (next: boolean) => void;
	} = $props();
</script>

<label class="option" class:option--checked={checked}>
	{#if type === 'checkbox'}
		<input
			type="checkbox"
			class="native-input"
			{checked}
			onchange={(e) => onChange(e.currentTarget.checked)}
		/>
		<span class="control checkbox-control" aria-hidden="true">
			{#if checked}
				<span class="checkmark">✓</span>
			{/if}
		</span>
	{:else}
		<input
			type="radio"
			{name}
			{value}
			class="native-input"
			{checked}
			onchange={() => onChange(true)}
		/>
		<span class="control radio-control" aria-hidden="true">
			{#if checked}
				<span class="radio-dot"></span>
			{/if}
		</span>
	{/if}
	<span class="option-label">{label}</span>
</label>

<style lang="scss">
	@use '$lib/styles/forms';

	.option {
		@include forms.option;
	}

	.option--checked {
		@include forms.option-checked;
	}

	.option--checked .control {
		@include forms.option-control-checked;
	}

	.control {
		@include forms.option-control;
	}

	.checkbox-control {
		border-radius: var(--radius-sm);
	}

	.radio-control {
		border-radius: 50%;
	}

	.checkmark {
		font-size: var(--font-size-sm);
		font-weight: 700;
		line-height: 1;
	}

	.radio-dot {
		width: 0.5rem;
		height: 0.5rem;
		border-radius: 50%;
		background: var(--color-tile-ink);
	}

	.option-label {
		font-weight: 600;
	}

	.native-input {
		@include forms.native-input-overlay;
	}
</style>
