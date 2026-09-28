<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { TABLE_CODE_LENGTH } from '$lib/table/table-code';

	let {
		code = $bindable(),
		codeValid,
		onSubmit
	}: { code: string; codeValid: boolean; onSubmit: () => void } = $props();
</script>

<section class="panel join-panel" aria-labelledby="join-heading">
	<h2 id="join-heading">{m.joinByCodePanel_heading()}</h2>
	<form
		onsubmit={(event) => {
			event.preventDefault();
			onSubmit();
		}}
	>
		<input
			id="join-code"
			type="text"
			data-testid="join-by-code-input"
			autocomplete="off"
			spellcheck="false"
			maxlength={TABLE_CODE_LENGTH}
			placeholder={m.joinByCodePanel_codePlaceholder()}
			aria-label={m.joinByCodePanel_codeAriaLabel()}
			bind:value={code}
		/>
		<button type="submit" class="primary" data-testid="join-by-code-submit" disabled={!codeValid}
			>{m.joinByCodePanel_submitButton()}</button
		>
	</form>
	<p class="hint">
		{m.joinByCodePanel_hint()}
	</p>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel {
		background: var(--color-surface);
		padding: var(--space-5);
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		@include buttons.panel-elevated;
	}

	.panel h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.hint {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	form {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
		align-items: center;
	}

	input {
		font-family: monospace;
		font-size: var(--font-size-lg);
		letter-spacing: 0.15em;
		text-transform: uppercase;
		color: var(--color-text);
		padding: var(--space-2) var(--space-3);
		width: 12ch;
		@include buttons.input-recessed;
	}

	input:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}

	button {
		font: inherit;
		padding: var(--space-2) var(--space-4);
		min-height: var(--tap-target-min);
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	button.primary {
		@include buttons.btn-primary;
	}
</style>
