<script lang="ts">
	import { TILE_ASSET, hasTileArt, type TileCode } from './tile-code';

	// `null` = concealed (render the back), matching the opponent-hand convention in
	// docs/03-frontend.md §4 (positional slots have no known tile until reveal).
	let { code = null }: { code?: TileCode | null } = $props();

	// plain <img src> rather than inlining the SVG markup (docs/03-frontend.md §7 suggests
	// inline/`<use>`): the vendored FluffyStuff files carry non-namespaced ids
	// (clipPath/filter/gradient) that collide across repeated inline copies of the same or
	// different tiles — a hand has many duplicate tile codes on screen at once. <img> gives
	// each instance an isolated rendering context, at the cost of not being stylable via
	// currentColor/CSS — revisit if that's needed later.
	const BACK_SRC = '/tiles/Back.svg';

	let src = $derived(
		code !== null && hasTileArt(code) ? `/tiles/${TILE_ASSET[code]}.svg` : BACK_SRC
	);
	let alt = $derived(code !== null && hasTileArt(code) ? `${code} tile` : 'concealed tile');
</script>

<img class="tile-face" {src} {alt} draggable="false" />

<style lang="scss">
	.tile-face {
		display: block;
		height: 100%;
		width: auto;
		user-select: none;
	}
</style>
