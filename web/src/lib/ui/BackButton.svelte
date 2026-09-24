<script lang="ts">
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

{#snippet icon()}
	<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
		<path
			d="M15 6 L9 12 L15 18"
			fill="none"
			stroke="currentColor"
			stroke-width="2"
			stroke-linecap="round"
			stroke-linejoin="round"
		/>
	</svg>
{/snippet}

{#if href}
	<a class="back-button" {href}>
		{@render icon()}
		<span>{label}</span>
	</a>
{:else}
	<button type="button" class="back-button" {onclick}>
		{@render icon()}
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

		svg {
			width: 18px;
			height: 18px;
			flex-shrink: 0;
		}
	}
</style>
