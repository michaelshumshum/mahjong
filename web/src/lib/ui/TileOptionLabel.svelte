<script lang="ts">
	import TileFace from '$lib/table/TileFace.svelte';
	import type { TileCode } from '$lib/table/tile-code';
	import { distinctTiles } from '$lib/table/tile-name';

	// the button carrying this sets aria-label (tileOptionAriaLabel); the previews are decorative.
	let { label, tiles = [] }: { label: string; tiles?: readonly TileCode[] } = $props();
</script>

{#if tiles.length}
	<span class="tile-option-tiles" aria-hidden="true">
		{#each distinctTiles(tiles) as code (code)}
			<span class="tile-option-tile"><TileFace {code} /></span>
		{/each}
	</span>
{/if}
<span class="tile-option-label">{label}</span>

<style lang="scss">
	.tile-option-tiles {
		display: inline-flex;
		gap: 2px;
		margin-inline-end: var(--space-2);
		vertical-align: middle;
	}

	.tile-option-tile {
		display: inline-flex;
		height: 1.75rem;
	}

	.tile-option-label {
		vertical-align: middle;
	}
</style>
