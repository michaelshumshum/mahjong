<script lang="ts" generics="T extends string">
	// a radio group drawn as one segmented bar; the selected option's description sits below it.
	let {
		legend,
		name,
		options,
		value,
		onChange
	}: {
		legend: string;
		name: string;
		options: { value: T; label: string; description?: string }[];
		value: T;
		onChange: (next: T) => void;
	} = $props();

	const uid = $props.id();
	const description = $derived(options.find((o) => o.value === value)?.description);
</script>

<fieldset class="segmented">
	<legend>{legend}</legend>
	<div class="segments">
		{#each options as option (option.value)}
			<label class="segment" class:segment--checked={option.value === value}>
				<input
					type="radio"
					class="native-input"
					{name}
					value={option.value}
					checked={option.value === value}
					aria-describedby={description ? `${uid}-desc` : undefined}
					onchange={() => onChange(option.value)}
				/>
				<span>{option.label}</span>
			</label>
		{/each}
	</div>
	{#if description}
		<p class="segmented-desc" id="{uid}-desc">{description}</p>
	{/if}
</fieldset>

<style lang="scss">
	@use '$lib/styles/forms';
	@use '$lib/styles/a11y';

	.segmented {
		@include forms.form-group;
		gap: var(--space-2);
	}

	legend {
		@include forms.settings-legend;
	}

	.segments {
		display: flex;
		gap: 2px;
		padding: 3px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.segment {
		position: relative;
		flex: 1 1 0;
		display: flex;
		align-items: center;
		justify-content: center;
		min-width: 0;
		min-height: 44px;
		padding: var(--space-2) var(--space-2);
		border-radius: calc(var(--radius-md) - 3px);
		color: var(--color-text-muted);
		font-weight: 600;
		font-size: var(--font-size-sm);
		line-height: 1.2;
		text-align: center;
		cursor: pointer;

		@include a11y.motion-ok {
			transition:
				background-color var(--dur-control) ease,
				color var(--dur-control) ease;
		}

		&:hover:not(.segment--checked) {
			background: rgb(255 255 255 / 0.05);
			color: var(--color-text);
		}

		&:focus-within {
			outline: 2px solid var(--color-brass);
			outline-offset: 1px;
		}
	}

	.segment--checked {
		background: var(--color-brass);
		color: var(--color-tile-ink);
	}

	.segmented-desc {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.native-input {
		@include forms.native-input-overlay;
	}
</style>
