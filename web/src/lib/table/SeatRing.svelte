<script lang="ts">
	import type { Seat } from '$lib/game/types';
	import type { WireSeatStatus } from '$lib/net/protocol';
	import { seatWind, WIND_CHAR } from './wind';
	import CompassFelt from './CompassFelt.svelte';
	import SeatRingSlot from './SeatRingSlot.svelte';
	import SeatOccupancySlot from './SeatOccupancySlot.svelte';

	let {
		you,
		dealer,
		seatStatus,
		names
	}: { you: Seat; dealer: Seat; seatStatus: WireSeatStatus[]; names: (string | null)[] } = $props();

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
	@use '$lib/styles/layout';

	@include layout.seat-ring(5.5rem);
</style>
