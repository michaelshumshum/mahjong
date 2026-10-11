<script lang="ts">
	import TileFace from './TileFace.svelte';
	import { tileName } from './tile-name';
	import type { MockSeatState } from './mock-game-state';
	import { m } from '$lib/paraglide/messages.js';

	// tablet-up: all four pools box the centre hub, `position` picking the side and rotation;
	// phone: each sits under its own seat (docs/frontend.md §3).
	let {
		seat,
		position,
		ariaLabel,
		lastDiscardIndex = null
	}: {
		seat: MockSeatState;
		position: 'across' | 'left' | 'right' | 'self';
		ariaLabel: string;
		lastDiscardIndex?: number | null;
	} = $props();
</script>

<div class="discard-pool discard-pool--{position}" role="list" aria-label={ariaLabel}>
	{#each seat.discards as code, i (i)}
		<div
			class="discard-tile"
			class:discard-tile--last={i === lastDiscardIndex}
			role="listitem"
			aria-label={m.centerDiscardPool_tileAriaLabel({ name: seat.name, tile: tileName(code) })}
			title={i === lastDiscardIndex
				? m.centerDiscardPool_lastDiscardTitle({ name: seat.name })
				: undefined}
		>
			<TileFace {code} />
		</div>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/layout';
	@use '$lib/styles/a11y';

	// tracks are sized to the tile's own footprint (long edge --discard-h, short edge
	// --discard-w) so every pool, rotated or not, gets the same 2px gap between tiles.
	.discard-pool {
		--discard-h: clamp(30px, 3.2cqi, 44px);
		--discard-w: calc(var(--discard-h) * 3 / 4);
		display: grid;
		grid-template-columns: repeat(6, var(--discard-w));
		gap: 2px;
	}

	.discard-tile {
		height: var(--discard-h);
	}

	// no thickness/drop shadow here: it bleeds onto the next row of the pool.
	.discard-tile :global(.tile-face) {
		height: 100%;
		box-shadow: none;
	}

	// landing settle: a short slide from the discarder's side plus the scale pulse. translate/
	// scale are independent of `transform`, so this composes with the side pools' own rotate.
	.discard-tile--last :global(.tile-face) {
		@include a11y.motion-ok {
			animation: discard-landing var(--dur-3) var(--ease-place);
		}
	}

	@keyframes discard-landing {
		from {
			translate: var(--discard-enter-x, 0) var(--discard-enter-y, 0);
			scale: 1.16;
			opacity: 0.6;
		}
		to {
			translate: 0 0;
			scale: 1;
			opacity: 1;
		}
	}

	.discard-pool--across .discard-tile--last :global(.tile-face) {
		--discard-enter-y: -10px;
	}

	.discard-pool--left .discard-tile--last :global(.tile-face) {
		--discard-enter-x: -10px;
	}

	.discard-pool--right .discard-tile--last :global(.tile-face) {
		--discard-enter-x: 10px;
	}

	.discard-pool--self .discard-tile--last :global(.tile-face) {
		--discard-enter-y: 10px;
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
			grid-template-columns: repeat(12, var(--discard-w));
		}
	}

	// rotated to read parallel to that seat's hand strip, same paint-only technique as
	// OpponentRegion. Declared after the shared rules above so these overrides win.
	.discard-pool--left,
	.discard-pool--right {
		@include layout.tablet-up {
			grid-template-columns: none;
			grid-template-rows: repeat(6, var(--discard-w));
			grid-auto-columns: var(--discard-h);
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
			width: var(--discard-h);
			height: var(--discard-w);
		}
	}

	.discard-pool--left .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: var(--discard-h);
			transform: translate(-50%, -50%) rotate(90deg);
		}
	}

	.discard-pool--right .discard-tile :global(.tile-face) {
		@include layout.tablet-up {
			position: absolute;
			top: 50%;
			left: 50%;
			height: var(--discard-h);
			transform: translate(-50%, -50%) rotate(-90deg);
		}
	}

	// phone: each pool is a wrapping row under its own seat (layout.seat-region-grid's pool-*
	// areas); an opponent's pool tucks into the gap and reads as the bottom of its chip.
	@include layout.phone-only {
		.discard-pool {
			display: flex;
			flex-wrap: wrap;
			align-content: flex-start;
			min-width: 0;
			min-height: calc(var(--discard-h) + var(--space-1));
			padding: 0 var(--space-2) var(--space-1);
			border-radius: 0 0 var(--radius-md) var(--radius-md);
			background: rgb(0 0 0 / 0.18);
		}

		.discard-pool--across {
			grid-area: pool-across;
		}

		.discard-pool--left {
			grid-area: pool-left;
		}

		.discard-pool--right {
			grid-area: pool-right;
		}

		.discard-pool--self {
			grid-area: pool-self;
			align-self: end;
			min-height: calc(var(--discard-h) + 2 * var(--space-1));
			padding-block-start: var(--space-1);
			border-radius: var(--radius-md);
		}

		.discard-pool:not(.discard-pool--self) {
			margin-block-start: calc(-1 * var(--space-1));
		}

		.discard-tile {
			width: var(--discard-w);
		}
	}

	@include layout.phone-landscape {
		.discard-pool {
			--discard-h: 26px;
		}

		// under the hub, not on the hand bar: a crowded side column scrolls the surface, and the
		// sticky bar would then cover a bottom-aligned pool.
		.discard-pool--self {
			align-self: start;
		}
	}
</style>
