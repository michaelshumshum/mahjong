<script lang="ts">
	import TileFace from './TileFace.svelte';
	import type { MockSeatState } from './mock-game-state';

	// all four discard pools live in the centre box (docs/frontend.md §3); `position` picks
	// the box side and, for left/right, the rotation matching that seat's own hand.
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
		grid-template-columns: repeat(6, minmax(26px, 36px));
		gap: 2px;
		max-width: 14rem;
	}

	.discard-tile {
		height: clamp(30px, 3.2vw, 44px);
	}

	.discard-tile :global(.tile-face) {
		height: 100%;
	}

	.discard-pool--across {
		@include layout.tablet-up {
			grid-area: across;
			align-self: start;
			justify-self: center;
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

	// wider than 6 columns so a long hand's discards wrap onto fewer rows -- unbounded row growth
	// here pushes the self seat region off-screen.
	.discard-pool {
		@include layout.tablet-up {
			grid-template-columns: repeat(12, minmax(26px, 36px));
			max-width: 26rem;
		}
	}

	.discard-tile {
		@include layout.tablet-up {
			height: clamp(30px, 3.2vw, 44px);
		}
	}

	// rotated to read parallel to that seat's hand strip, same paint-only technique as
	// OpponentRegion. Declared after the shared rules above so these overrides win.
	.discard-pool--left,
	.discard-pool--right {
		@include layout.tablet-up {
			grid-template-columns: none;
			grid-template-rows: repeat(6, minmax(30px, 40px));
			grid-auto-flow: column;
		}
	}

	// grid auto-placement advances toward higher indices, which reads as "away from centre" for
	// --right; `direction: rtl` flips the wrap direction without touching tile positioning.
	.discard-pool--right {
		@include layout.tablet-up {
			direction: rtl;
		}
	}

	// grid's row-major wrap pushes overflow further down the page -- wrong for self (the bottom
	// edge); scaleY(-1) flips the grid so overflow reads as growing upward, toward centre.
	.discard-pool--self {
		@include layout.tablet-up {
			transform: scaleY(-1);
			align-self: end;
			justify-self: center;
		}
	}

	.discard-pool--self .discard-tile {
		@include layout.tablet-up {
			transform: scaleY(-1);
		}
	}

	.discard-pool--left .discard-tile,
	.discard-pool--right .discard-tile {
		@include layout.tablet-up {
			position: relative;
			width: clamp(30px, 3.2vw, 44px);
			height: calc(clamp(30px, 3.2vw, 44px) * 3 / 4);
		}
	}

	.discard-pool--left .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(30px, 3.2vw, 44px);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.discard-pool--right .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: clamp(30px, 3.2vw, 44px);
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
