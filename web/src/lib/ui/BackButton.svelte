<script lang="ts">
	import ChevronLeft from '@lucide/svelte/icons/chevron-left';

	// shared top-left "go back"/"leave" affordance so icon, label placement, and position stay
	// identical across every route that uses it.
	let {
		label,
		href,
		onclick
	}: {
		label: string;
		href?: string;
		onclick?: () => void;
	} = $props();
</script>

{#if href}
	<a class="back-button" data-sfx="on" {href}>
		<ChevronLeft size={18} />
		<span>{label}</span>
	</a>
{:else}
	<button type="button" class="back-button" {onclick}>
		<ChevronLeft size={18} />
		<span>{label}</span>
	</button>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.back-button {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		align-self: flex-start;
		min-height: var(--tap-target-min);
		padding: var(--space-1) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		text-decoration: none;
		cursor: pointer;
		@include buttons.btn-secondary;

		:global(svg) {
			flex-shrink: 0;
		}
	}
</style>
