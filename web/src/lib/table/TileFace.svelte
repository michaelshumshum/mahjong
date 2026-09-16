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

<span class="tile-face">
	<img {src} {alt} draggable="false" />
</span>

<style lang="scss">
	// physical-tile treatment (docs/03-frontend.md is silent on this — this sub-task's call):
	// the vendored art is glyph-only on a transparent canvas, so an ivory background sits
	// behind it here, clipped to --radius-tile. The background-color and the <img> each clip
	// to border-radius through a different rendering path (CSS background-clip vs. replaced-
	// element content clip) and can anti-alias the curve by a fractional pixel differently,
	// leaving a sliver of ivory visible right at the corners — an `overflow: hidden` wrapper
	// clips both through the same box, so there's nothing left to mismatch.
	.tile-face {
		display: inline-flex;
		height: 100%;
		width: auto;
		overflow: hidden;
		border-radius: var(--radius-tile);
		background: var(--color-tile);
		box-shadow:
			0 1px 2px rgb(0 0 0 / 0.35),
			inset 0 0 0 1px rgb(36 27 20 / 0.35),
			inset 0 -2px 3px rgb(36 27 20 / 0.18);
	}

	.tile-face img {
		display: block;
		height: 100%;
		width: auto;
		user-select: none;
	}
</style>
