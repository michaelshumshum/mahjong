<!-- indeterminate wait (still connecting): no deadline to anchor a TimerRing to. -->
<div class="spinner"></div>

<style lang="scss">
	@use '$lib/styles/a11y';

	.spinner {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 3px solid var(--color-border);
		border-top-color: var(--color-accent);
		animation: spin var(--dur-spin) linear infinite;

		@include a11y.motion-reduced {
			animation: none;
			opacity: 0.6;
		}
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}
</style>
