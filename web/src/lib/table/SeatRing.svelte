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

<!-- Seated pre-game preview (docs/03-frontend.md's "/table/[id] wiring" pre-game states). Same
	across/left/right/self arrangement the real table grid uses (§3), previewed at token scale
	before any hand exists. Self is the one seat this screen already knows a real wind for (the
	dealer is fixed at table construction, before any `ready`). The other three show real live
	occupancy instead (`seatStatus`/`names`, kept current via `seat_state` broadcasts the same
	way the seat picker reads them pre-join) -- so a seated player watching this screen sees the
	next arrival land, not just a placeholder that never changes. -->
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
