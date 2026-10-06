<script lang="ts">
	import { TILE_ASSET, hasTileArt, type TileCode } from './tile-code';
	import { tileName } from './tile-name';
	import { m } from '$lib/paraglide/messages.js';

	// `null` = concealed (render the back).
	let { code = null }: { code?: TileCode | null } = $props();

	// plain <img src>, not inlined SVG: the vendored files carry non-namespaced ids that collide
	// across repeated inline copies of the same tile. Costs currentColor/CSS stylability.
	const BACK_SRC = '/tiles/Back.svg';

	let face = $derived(code !== null && hasTileArt(code) ? code : null);
	let src = $derived(face !== null ? `/tiles/${TILE_ASSET[face]}.svg` : BACK_SRC);
	let alt = $derived(face !== null ? tileName(face) : m.tileFace_concealedTileAlt());
</script>

<!-- data-tile: a locale-independent hook for specs, since alt is now a localized name -->
<span class="tile-face" class:tile-face--back={face === null} data-tile={face}>
	<img {src} {alt} draggable="false" />
</span>

<style lang="scss">
	// background-color and <img> each clip to border-radius through a different rendering path
	// and can anti-alias the corner differently -- overflow: hidden clips both through one box.
	.tile-face {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		aspect-ratio: 3 / 4;
		overflow: hidden;
		border-radius: calc(var(--radius-tile) * 4 / 3) / var(--radius-tile);
		background: var(--color-tile);
		box-shadow:
			0 1px 2px rgb(0 0 0 / 0.35),
			inset 0 0 0 1px rgb(36 27 20 / 0.35),
			inset 0 -2px 3px rgb(36 27 20 / 0.18);
	}

	.tile-face img {
		display: block;
		height: 100%;
		width: 100%;
		padding: 7%;
		box-sizing: border-box;
		object-fit: contain;
		user-select: none;
	}

	.tile-face--back img {
		padding: 0;
	}

	.tile-face--back {
		background: none;
		box-shadow: 0 1px 2px rgb(0 0 0 / 0.35);
	}
</style>
