<script lang="ts">
	import type { Seat } from '$lib/game/types';
	import type { WireSeatStatus } from '$lib/net/protocol';
	import CompassFelt from './CompassFelt.svelte';
	import SeatPickerSlot from './SeatPickerSlot.svelte';

	let {
		seatStatus,
		names,
		onJoin
	}: { seatStatus: WireSeatStatus[]; names: (string | null)[]; onJoin: (seat: Seat) => void } =
		$props();
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
	@use '$lib/styles/layout';

	@include layout.seat-ring(5.5rem);
</style>
