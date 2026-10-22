<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { faanPatternLabel } from './faan-pattern-labels';
	import { patternInfo } from './faan-guide';

	// `onSelect` given: a known pattern renders as a button that opens it in the faan guide.
	let { name, onSelect }: { name: string; onSelect?: (name: string) => void } = $props();

	let label = $derived(faanPatternLabel(name));
	let linkable = $derived(onSelect !== undefined && patternInfo(name) !== undefined);
</script>

{#if linkable}
	<button
		type="button"
		class="pattern-link"
		title={m.guide_openPatternTitle()}
		data-testid="faan-pattern-link"
		onclick={() => onSelect?.(name)}>{label}</button
	>
{:else}
	<span>{label}</span>
{/if}

<style lang="scss">
	.pattern-link {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		color: inherit;
		text-align: start;
		text-decoration: underline dotted;
		text-decoration-color: var(--color-text-muted);
		text-underline-offset: 3px;
		cursor: pointer;

		&:hover {
			text-decoration-color: var(--color-brass);
		}
	}
</style>
