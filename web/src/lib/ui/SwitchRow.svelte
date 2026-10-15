<script lang="ts">
	let {
		label,
		description,
		checked,
		disabled = false,
		onChange
	}: {
		label: string;
		description?: string;
		checked: boolean;
		disabled?: boolean;
		onChange: (next: boolean) => void;
	} = $props();

	const uid = $props.id();
</script>

<label class="switch-row" class:switch-row--disabled={disabled}>
	<span class="switch-text">
		<span class="switch-label">{label}</span>
		{#if description}
			<span class="switch-desc" id="{uid}-desc">{description}</span>
		{/if}
	</span>
	<input
		type="checkbox"
		role="switch"
		class="native-input"
		{checked}
		{disabled}
		aria-describedby={description ? `${uid}-desc` : undefined}
		onchange={(e) => onChange(e.currentTarget.checked)}
	/>
	<span class="track" class:track--on={checked} aria-hidden="true">
		<span class="thumb"></span>
	</span>
</label>

<style lang="scss">
	@use '$lib/styles/forms';
	@use '$lib/styles/a11y';

	.switch-row {
		position: relative;
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		min-height: 44px;
		padding: var(--space-3) var(--space-1);
		cursor: pointer;

		&:focus-within .track {
			outline: 2px solid var(--color-brass);
			outline-offset: 2px;
		}
	}

	.switch-row--disabled {
		cursor: not-allowed;
		opacity: 0.5;
	}

	.switch-row + :global(.switch-row) {
		border-top: 1px solid var(--color-border);
	}

	.switch-text {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.switch-label {
		font-weight: 600;
	}

	.switch-desc {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.track {
		flex: none;
		position: relative;
		width: 2.75rem;
		height: 1.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-pill);
		background: var(--color-surface);
		pointer-events: none;

		@include a11y.motion-ok {
			transition:
				background-color 150ms ease,
				border-color 150ms ease;
		}
	}

	.thumb {
		position: absolute;
		top: 2px;
		left: 2px;
		width: calc(1.5rem - 6px);
		height: calc(1.5rem - 6px);
		border-radius: 50%;
		background: var(--color-text-muted);

		@include a11y.motion-ok {
			transition:
				translate 150ms ease,
				background-color 150ms ease;
		}
	}

	.track--on {
		border-color: var(--color-brass);
		background: var(--color-brass);

		.thumb {
			translate: 1.25rem 0;
			background: var(--color-tile-ink);
		}
	}

	.native-input {
		@include forms.native-input-overlay;
	}
</style>
