<script lang="ts">
	let { label, self = false }: { label: string; self?: boolean } = $props();
</script>

<div class="seat-ring-slot" class:seat-ring-slot--self={self}>
	<span>{label}</span>
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
		// "waiting, alive" -- the base/default treatment for a genuinely open seat
		// (server/app/table.py's `_seat_status_tuple` reports `empty` for one, distinct from
		// `connected`/`bot`/`disconnected`/`autoplay`), so this animation now means what it
		// looks like: nobody's here yet, but the table is open and listening.
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// the one seat this screen actually knows something real about: dealer is fixed at table
	// creation, so once you're seated your own wind is true today, not a guess.
	.seat-ring-slot--self {
		border: 1px solid var(--color-accent);
		background: color-mix(in srgb, var(--color-accent) 16%, transparent);
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
