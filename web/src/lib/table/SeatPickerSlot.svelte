<script lang="ts">
	import type { Seat } from '$lib/game/types';
	import { m } from '$lib/paraglide/messages.js';

	let {
		seat,
		self = false,
		status,
		name,
		onJoin
	}: {
		seat: Seat;
		self?: boolean;
		status: string;
		name: string | null;
		onJoin: (seat: Seat) => void;
	} = $props();
	let open = $derived(status === 'empty');
</script>

<button
	type="button"
	class="seat-ring-slot"
	class:seat-ring-slot--self={self}
	class:seat-ring-slot--open={open}
	disabled={!open}
	onclick={() => onJoin(seat)}
>
	<span
		>{open
			? m.seatPickerSlot_openLabel()
			: status === 'bot'
				? m.seatPickerSlot_botLabel()
				: (name ?? m.seatPickerSlot_takenLabel())}</span
	>
</button>

<style lang="scss">
	// same treatment as the table cards' compass seats (TableCard): an open seat is a dashed
	// pill (here accent-tinted since it's the click target), a taken seat is plain bold text.
	.seat-ring-slot {
		font: inherit;
		background: none;
		max-width: 100%;
		padding: var(--space-1) var(--space-2);
		border: none;
		color: var(--color-text);
		font-size: var(--font-size-sm);
		font-weight: 600;
		white-space: nowrap;

		span {
			overflow: hidden;
			text-overflow: ellipsis;
			user-select: none;
		}

		&:disabled {
			cursor: default;
			opacity: 0.7;
		}
	}

	// self carries no emphasis here: all four seats are identical choices until you pick one.
	// (the --self class stays for SeatPickerSlot.spec and for seat-order parity with SeatRing.)
	.seat-ring-slot--open {
		padding: var(--space-1) var(--space-3);
		border: 1px dashed var(--color-accent);
		border-radius: var(--radius-pill);
		cursor: pointer;

		&:hover {
			background: color-mix(in srgb, var(--color-accent) 12%, transparent);
		}
	}
</style>
