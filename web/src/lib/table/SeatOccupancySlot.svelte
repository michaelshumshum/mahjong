<script lang="ts">
	let { status, name }: { status: string; name: string | null } = $props();
	let open = $derived(status === 'empty');
</script>

<div class="seat-ring-slot" class:seat-ring-slot--filled={!open}>
	<span>{open ? 'Open' : status === 'bot' ? 'Bot' : (name ?? 'Taken')}</span>
</div>

<style lang="scss">
	.seat-ring-slot {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: 50%;
		border: 1px dashed var(--color-border);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// occupancy is real (spectator state_sync, kept live via seat_state) -- a filled seat reads
	// solid/inert rather than still breathing "open," same visual language as SeatRingSlot's own
	// --self.
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
