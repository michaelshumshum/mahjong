<script lang="ts">
	import type { Seat } from './mock-game-state';
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
