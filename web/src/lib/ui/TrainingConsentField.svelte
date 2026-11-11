<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';

	// a wording change bumps the server's TRAINING_CONSENT_VERSION (docs/protocol.md §10)
	let {
		checked,
		disabled = false,
		onChange
	}: { checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void } = $props();
</script>

<label class="consent" data-testid="training-consent">
	<input
		type="checkbox"
		{checked}
		{disabled}
		onchange={(event) => onChange(event.currentTarget.checked)}
	/>
	<span class="label">{m.trainingConsentField_label()}</span>
</label>

<style lang="scss">
	@use '$lib/styles/forms';

	.consent {
		display: flex;
		align-items: flex-start;
		gap: var(--space-3);
		text-align: start;
		cursor: pointer;
	}

	// OptionRow's box, drawn on the real input so focus and keyboard stay native
	input {
		@include forms.option-control;
		position: relative;
		margin: 2px 0 0;
		border-radius: var(--radius-sm);
		background: transparent;
		appearance: none;
		pointer-events: auto;
		cursor: pointer;

		&:checked {
			@include forms.option-control-checked;
		}

		&:checked::after {
			content: '';
			position: absolute;
			top: 0.1rem;
			left: 0.32rem;
			width: 0.3rem;
			height: 0.6rem;
			border: solid var(--color-tile-ink);
			border-width: 0 2px 2px 0;
			transform: rotate(45deg);
		}

		&:focus-visible {
			outline: 2px solid var(--color-accent);
			outline-offset: 2px;
		}

		&:disabled {
			opacity: 0.5;
			cursor: not-allowed;
		}
	}

	.consent:hover input:not(:checked, :disabled) {
		border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border) 55%);
	}

	.label {
		@include forms.field-label;
	}
</style>
