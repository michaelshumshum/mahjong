<script lang="ts">
	import TileFace from './TileFace.svelte';
	import { meldTileFace } from './meld-face';
	import type { TileCode } from './tile-code';
	import type { MeldView } from './view-types';

	// a seat's flower group then its melds; the parent's .meld-row is the flex row they sit in.
	let {
		flowers,
		melds,
		flowersLabel
	}: { flowers: TileCode[]; melds: MeldView[]; flowersLabel: string } = $props();
</script>

{#if flowers.length}
	<div class="meld" aria-label={flowersLabel}>
		{#each flowers as code, i (i)}
			<div class="mini-tile"><TileFace {code} /></div>
		{/each}
	</div>
{/if}
{#each melds as meld, mi (mi)}
	<div class="meld">
		{#each meld.tiles as code, ti (ti)}
			<div class="mini-tile">
				<TileFace code={meldTileFace(meld.kind, code, ti, meld.tiles.length)} />
			</div>
		{/each}
	</div>
{/each}

<style lang="scss">
	@use '$lib/styles/tile';

	.mini-tile {
		@include tile.mini-tile;
	}

	.meld {
		@include tile.meld;
		@include tile.meld-enter;
	}
</style>
