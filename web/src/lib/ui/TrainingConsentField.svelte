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

	input {
		flex: none;
		width: 1.25rem;
		height: 1.25rem;
		margin: 2px 0 0;
		accent-color: var(--color-accent);
	}

	.label {
		@include forms.field-label;
	}
</style>
