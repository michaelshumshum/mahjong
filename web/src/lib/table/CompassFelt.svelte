<script lang="ts">
	import { SEAT_WINDS, WIND_CHAR } from './wind';

	// rotate = viewer's wind index (E=0 … N=3): shifts glyphs so their wind sits at the bottom
	// edge. 0 (table cards) is purely decorative; the seated waiting ring passes a real rotation.
	let { rotate = 0 }: { rotate?: number } = $props();
	let winds = $derived([0, 1, 2, 3].map((p) => WIND_CHAR[SEAT_WINDS[(p + rotate) % 4]]));
</script>

<!-- Mini felt square with the four wind glyphs, each rotated to read from its own seat's side.
	Shared by the table cards, the pre-game seat rings and the practice setup dialog so all three
	read as the same table seen from above; sizes itself to its container. -->
<div class="compass-felt" aria-hidden="true">
	{#each winds as glyph, i (i)}
		<span class="wind wind--{i}">{glyph}</span>
	{/each}
</div>

<style lang="scss">
	.compass-felt {
		position: relative;
		user-select: none;
		width: 100%;
		aspect-ratio: 1;
		border: 2px solid var(--color-rim-hi);
		border-radius: var(--radius-sm);
		background: radial-gradient(circle at 50% 40%, var(--color-felt-lit), var(--color-felt-deep));
		box-shadow: inset 0 0 0 1px var(--color-felt-line);
	}

	.wind {
		position: absolute;
		color: color-mix(in srgb, var(--color-felt-muted) 75%, transparent);
		font-size: var(--font-size-xs);
		font-weight: 600;
		line-height: 1;
	}

	.wind--0 {
		bottom: 4px;
		left: 50%;
		transform: translateX(-50%);
	}

	.wind--1 {
		right: 4px;
		top: 50%;
		transform: translateY(-50%) rotate(-90deg);
	}

	.wind--2 {
		top: 4px;
		left: 50%;
		transform: translateX(-50%) rotate(180deg);
	}

	.wind--3 {
		left: 4px;
		top: 50%;
		transform: translateY(-50%) rotate(90deg);
	}
</style>
