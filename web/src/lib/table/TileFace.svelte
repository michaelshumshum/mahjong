<script lang="ts">
	import { TILE_ASSET, hasTileArt, type TileCode } from './tile-code';
	import { tileName } from './tile-name';
	import { m } from '$lib/paraglide/messages.js';

	// `null` = concealed (render the back).
	let { code = null }: { code?: TileCode | null } = $props();

	let face = $derived(code !== null && hasTileArt(code) ? code : null);
	let src = $derived(face !== null ? `/tiles/${TILE_ASSET[face]}.svg` : null);
	let alt = $derived(face !== null ? tileName(face) : m.tileFace_concealedTileAlt());
</script>

<!-- data-tile: a locale-independent hook for specs, since alt is now a localized name.
     back has no image asset (CSS jade, see .tile-face--back); role/aria-label stand in for the
     alt text an <img> would otherwise carry. -->
<span
	class="tile-face"
	class:tile-face--back={face === null}
	data-tile={face}
	role={face === null ? 'img' : undefined}
	aria-label={face === null ? alt : undefined}
>
	{#if src}
		<img {src} {alt} draggable="false" />
	{/if}
</span>

<style lang="scss">
	// overflow: hidden clips background and <img> through one box, avoiding mismatched corner aa.
	// box-shadow layers (edge/side bands + drop shadow) give the face thickness, not a bevel.
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
			0 1px 0 var(--color-tile-edge),
			0 3px 0 var(--color-tile-side),
			0 5px 8px rgb(0 0 0 / 0.35);
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

	// jade back: a gradient standing in for the vendored Back.svg flat rect, with a lighter top
	// edge reading as the glazed ridge of a real tile back. Same thickness shadow as the face.
	.tile-face--back {
		background: linear-gradient(
			180deg,
			var(--color-tile-back-edge) 0%,
			var(--color-tile-back) 18%,
			var(--color-tile-back) 100%
		);
	}
</style>
