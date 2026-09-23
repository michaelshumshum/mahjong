<script lang="ts">
	import TileFace from './TileFace.svelte';
	import type { MockSeatState } from './mock-game-state';

	// All four discard pools live together in the centre (docs/03-frontend.md §3's "Discard pool
	// geometry"), forming a box around the middle of the table instead of sitting at each seat's
	// own edge -- matches the physical layout of discards piled in front of each player, in the
	// shared space between hands. `position` picks the box side and, for left/right, the rotation
	// that keeps each pool parallel to that seat's own (already-rotated) hand. The parent page
	// still owns the `.table-center` grid container itself; this component's root element is a
	// grid item inside it, so `grid-area` below is resolved purely by the real DOM/grid
	// relationship, with no need for the page's stylesheet to reach into this one.
	let {
		seat,
		position,
		ariaLabel
	}: {
		seat: MockSeatState;
		position: 'across' | 'left' | 'right' | 'self';
		ariaLabel: string;
	} = $props();
</script>

<div class="discard-pool discard-pool--{position}" role="list" aria-label={ariaLabel}>
	{#each seat.discards as code, i (i)}
		<div class="discard-tile" role="listitem"><TileFace {code} /></div>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.discard-pool {
		display: grid;
		grid-template-columns: repeat(6, minmax(20px, 28px));
		justify-content: start;
		gap: 2px;
		max-width: 14rem;
	}

	.discard-tile {
		height: clamp(22px, 3.5vw, 32px);
	}

	.discard-tile :global(.tile-face) {
		height: 100%;
	}

	.discard-pool--across {
		@include layout.tablet-up {
			grid-area: across;
		}
	}

	.discard-pool--left {
		@include layout.tablet-up {
			grid-area: left;
		}
	}

	.discard-pool--right {
		@include layout.tablet-up {
			grid-area: right;
		}
	}

	.discard-pool--self {
		@include layout.tablet-up {
			grid-area: self;
		}
	}

	// wider than the 6-column default so a long hand's discards wrap onto fewer rows -- unbounded
	// row growth here pushes the self seat region (in the parent page) down the page, off-screen,
	// since `.table-center`'s own middle column is `1fr` and has room to spare.
	.discard-pool {
		@include layout.tablet-up {
			grid-template-columns: repeat(12, minmax(20px, 28px));
			max-width: 26rem;
		}
	}

	.discard-tile {
		@include layout.tablet-up {
			height: clamp(26px, 4vw, 36px);
		}
	}

	// left/right box pools rotated to read parallel to that seat's own already-rotated hand strip
	// -- same box-stays-put/only-the-face-rotates technique as OpponentRegion's hand strip (paint-
	// only rotation, never changes what the grid measures), reused here for a grid of discards
	// instead of a flex row of hand tiles. Declared after the shared `.discard-pool`/`.discard-tile`
	// rules above so these equal-specificity overrides win on `grid-template-columns`/height.
	.discard-pool--left,
	.discard-pool--right {
		@include layout.tablet-up {
			grid-template-columns: none;
			grid-template-rows: repeat(6, minmax(24px, 32px));
			grid-auto-flow: column;
		}
	}

	.discard-pool--left .discard-tile,
	.discard-pool--right .discard-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(26px, 4vw, 36px);
			height: calc(clamp(26px, 4vw, 36px) * 3 / 4);
		}
	}

	.discard-pool--left .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(26px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.discard-pool--right .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(26px, 4vw, 36px);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	@include layout.phone-only {
		.discard-pool {
			grid-template-columns: none;
			grid-auto-flow: column;
			grid-auto-columns: minmax(22px, 28px);
			overflow-x: auto;
			max-width: 100%;
		}
	}
</style>
