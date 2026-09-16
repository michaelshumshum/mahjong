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
	// physical-tile treatment (docs/03-frontend.md is silent on this — this sub-task's call):
	// the vendored art is glyph-only on a transparent canvas, so an ivory background sits
	// behind it here, clipped to --radius-tile same as any replaced element. The concealed
	// back (Back.svg) already paints its own opaque fill edge-to-edge, so the ivory never
	// shows through it — same edge/bevel treatment either way, only the art differs, which is
	// the deliberate choice: one physical tile shape for the whole set.
	.tile-face {
		display: block;
		height: 100%;
		width: auto;
		user-select: none;
		background: var(--color-tile);
		border-radius: var(--radius-tile);
		box-shadow:
			0 1px 2px rgb(0 0 0 / 0.35),
			inset 0 0 0 1px rgb(36 27 20 / 0.35),
			inset 0 -2px 3px rgb(36 27 20 / 0.18);
	}
</style>
