<script lang="ts">
	import type { Seat } from './mock-game-state';
	import { seatWind, WIND_CHAR } from './wind';
	import SeatRingSlot from './SeatRingSlot.svelte';
	import SeatOccupancySlot from './SeatOccupancySlot.svelte';

	let {
		you,
		dealer,
		seatStatus,
		names
	}: { you: Seat; dealer: Seat; seatStatus: string[]; names: (string | null)[] } = $props();
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
</div>

<style lang="scss">
	.seat-ring {
		display: grid;
		grid-template-areas:
			'.      across .'
			'left   .      right'
			'.      self   .';
		grid-template-columns: repeat(3, 3.25rem);
		grid-template-rows: repeat(3, 3.25rem);
		gap: var(--space-1);
		place-items: center;
	}

	.seat-ring-pos--across {
		grid-area: across;
	}

	.seat-ring-pos--left {
		grid-area: left;
	}

	.seat-ring-pos--right {
		grid-area: right;
	}

	.seat-ring-pos--self {
		grid-area: self;
	}
</style>
