<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import X from '@lucide/svelte/icons/x';

	let { onclick }: { onclick: () => void } = $props();
</script>

<button
	type="button"
	class="close-btn"
	data-testid="close-button"
	aria-label={m.closeButton_ariaLabel()}
	{onclick}
>
	<X size={20} />
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
		min-height: var(--tap-target-min);
		min-width: var(--tap-target-min);
		padding: 0;
		cursor: pointer;
		@include buttons.btn-ghost;
	}
</style>
