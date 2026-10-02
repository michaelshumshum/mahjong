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
	.seat-ring-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		min-width: 2.75rem;
		min-height: 2.75rem;
		padding-inline: var(--space-2);
		border-radius: 50%;
		border: 1px dashed var(--color-border);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		white-space: nowrap;
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// occupancy is real -- a filled seat reads solid/inert rather than still breathing "open".
	.seat-ring-slot--filled {
		border: 1px solid var(--color-border);
		color: var(--color-text);
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

	@media (prefers-reduced-motion: reduce) {
		.seat-ring-slot {
			animation: none;
			opacity: 0.85;
		}
	}
</style>
