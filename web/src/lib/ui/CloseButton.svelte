<script lang="ts">
	let { onclick }: { onclick: () => void } = $props();
</script>

<button type="button" class="close-btn" aria-label="Close" {onclick}>
	<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
		<path
			d="M6 6 L18 18 M18 6 L6 18"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
		/>
	</svg>
</button>

<style lang="scss">
	@use '$lib/styles/buttons';

	.close-btn {
		position: absolute;
		top: var(--space-2);
		right: var(--space-2);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 44px;
		min-width: 44px;
		padding: 0;
		cursor: pointer;
		@include buttons.btn-ghost;
	}

	svg {
		width: 20px;
		height: 20px;
	}
</style>
