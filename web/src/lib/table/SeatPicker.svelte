<script lang="ts">
	import type { Seat } from './mock-game-state';
	import CompassFelt from './CompassFelt.svelte';
	import SeatPickerSlot from './SeatPickerSlot.svelte';

	let {
		seatStatus,
		names,
		onJoin
	}: { seatStatus: string[]; names: (string | null)[]; onJoin: (seat: Seat) => void } = $props();
</script>

<!-- Pre-join seat picker: connected as a spectator, so real seatStatus/names are already known --
	each slot is a specific seat you can click to `join` directly, laid out the same as SeatRing
	so the geometry doesn't jump once seated. -->
<div class="seat-ring">
	<div class="seat-ring-pos seat-ring-pos--across">
		<SeatPickerSlot
			seat={2 as Seat}
			status={seatStatus[2] ?? 'empty'}
			name={names[2] ?? null}
			{onJoin}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--left">
		<SeatPickerSlot
			seat={3 as Seat}
			status={seatStatus[3] ?? 'empty'}
			name={names[3] ?? null}
			{onJoin}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--right">
		<SeatPickerSlot
			seat={1 as Seat}
			status={seatStatus[1] ?? 'empty'}
			name={names[1] ?? null}
			{onJoin}
		/>
	</div>
	<div class="seat-ring-pos seat-ring-pos--self">
		<SeatPickerSlot
			seat={0 as Seat}
			self={true}
			status={seatStatus[0] ?? 'empty'}
			name={names[0] ?? null}
			{onJoin}
		/>
	</div>
	<div class="seat-ring-felt"><CompassFelt /></div>
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
