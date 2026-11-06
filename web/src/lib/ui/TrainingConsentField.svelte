<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';

	// a wording change bumps the server's TRAINING_CONSENT_VERSION (docs/protocol.md §10)
	let {
		checked,
		disabled = false,
		onChange
	}: { checked: boolean; disabled?: boolean; onChange: (checked: boolean) => void } = $props();

	const uid = $props.id();
</script>

<label class="consent" data-testid="training-consent">
	<input
		type="checkbox"
		{checked}
		{disabled}
		aria-describedby="{uid}-desc"
		onchange={(event) => onChange(event.currentTarget.checked)}
	/>
	<span class="text">
		<span class="label">{m.trainingConsentField_label()}</span>
		<span class="desc" id="{uid}-desc">{m.trainingConsentField_description()}</span>
	</span>
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

	.text {
		@include forms.field-text;
	}

	.label {
		@include forms.field-label;
	}

	.desc {
		@include forms.field-desc;
	}
</style>
