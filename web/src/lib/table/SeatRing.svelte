<script lang="ts">
	import type { Seat } from '$lib/game/types';
	import { seatWind, WIND_CHAR } from './wind';
	import CompassFelt from './CompassFelt.svelte';
	import SeatRingSlot from './SeatRingSlot.svelte';
	import SeatOccupancySlot from './SeatOccupancySlot.svelte';

	let {
		you,
		dealer,
		seatStatus,
		names
	}: { you: Seat; dealer: Seat; seatStatus: string[]; names: (string | null)[] } = $props();

	// dealer is fixed at table creation, so your wind is real once seated: rotate the felt so it
	// sits at the bottom edge, matching the self slot below.
	let rotation = $derived((you - dealer + 4) % 4);
</script>

<!-- Seated pre-game preview, same seat arrangement the real table grid uses. Self is the one
	seat with a known real wind (dealer fixed at construction); the other three show real live
	occupancy so a seated player watches the next arrival land. -->
<div class="seat-ring" aria-hidden="true">
	<div class="seat-ring-pos seat-ring-pos--across">
		<SeatOccupancySlot
			status={seatStatus[(you + 2) % 4] ?? 'empty'}
			name={names[(you + 2) % 4] ?? null}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--left">
		<SeatOccupancySlot
			status={seatStatus[(you + 3) % 4] ?? 'empty'}
			name={names[(you + 3) % 4] ?? null}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--right">
		<SeatOccupancySlot
			status={seatStatus[(you + 1) % 4] ?? 'empty'}
			name={names[(you + 1) % 4] ?? null}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--self">
		<SeatRingSlot label={WIND_CHAR[seatWind(you, dealer)]} self={true} />
	</div>
	<div class="seat-ring-felt"><CompassFelt rotate={rotation} /></div>
</div>

<style lang="scss">
	// same compass layout as the table cards (TableCard): name labels above/below spanning the
	// full width, side seats in flexible columns flanking the mini felt (CompassFelt).
	.seat-ring {
		display: grid;
		grid-template-areas:
			'top   top  top'
			'left  felt right'
			'bottom bottom bottom';
		grid-template-columns: minmax(0, 1fr) auto minmax(0, 1fr);
		align-items: center;
		gap: var(--space-2);
		width: 100%;
	}

	.seat-ring-felt {
		grid-area: felt;
		width: 5.5rem;
	}

	.seat-ring-pos {
		display: flex;
		justify-content: center;
		min-width: 0;
	}

	.seat-ring-pos--across {
		grid-area: top;
	}

	.seat-ring-pos--left {
		grid-area: left;
		justify-content: flex-end;
	}

	.seat-ring-pos--right {
		grid-area: right;
		justify-content: flex-start;
	}

	.seat-ring-pos--self {
		grid-area: bottom;
	}
</style>
