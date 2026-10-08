<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';

	let { status, name }: { status: string; name: string | null } = $props();
	let open = $derived(status === 'empty');
</script>

<div class="seat-ring-slot" class:seat-ring-slot--filled={!open}>
	<span
		>{open
			? m.seatOccupancySlot_openLabel()
			: status === 'bot'
				? m.seatOccupancySlot_botLabel()
				: (name ?? m.seatOccupancySlot_takenLabel())}</span
	>
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	// open seats get the table cards' dashed-pill "Open" treatment; the breathing marks the
	// ring as live while waiting for players.
	.seat-ring-slot {
		max-width: 100%;
		padding: var(--space-1) var(--space-3);
		border: 1px dashed var(--color-border);
		border-radius: 999px;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		white-space: nowrap;
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
		user-select: none;

		span {
			overflow: hidden;
			text-overflow: ellipsis;
			user-select: none;
		}
	}

	// a filled seat is plain bold name text, like the table cards' compass names.
	.seat-ring-slot--filled {
		padding: var(--space-1) var(--space-2);
		border: none;
		color: var(--color-text);
		font-weight: 600;
		animation: none;
	}

	@keyframes seat-ring-breathe {
		0%,
		100% {
			opacity: 0.5;
		}
		50% {
			opacity: 1;
		}
	}

	.seat-ring-slot {
		@include a11y.motion-reduced {
			animation: none;
			opacity: 0.85;
		}
	}
</style>
