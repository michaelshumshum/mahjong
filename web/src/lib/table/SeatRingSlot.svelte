<script lang="ts">
	let { label, self = false }: { label: string; self?: boolean } = $props();
</script>

<div class="seat-ring-slot" class:seat-ring-slot--self={self}>
	<span>{label}</span>
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
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
		// "waiting, alive" -- the default treatment for a genuinely open (empty) seat.
		animation: seat-ring-breathe 2.4s ease-in-out infinite;
	}

	// dealer is fixed at table creation, so once seated your own wind is true, not a guess.
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

	.seat-ring-slot {
		@include a11y.motion-reduced {
			animation: none;
			opacity: 0.85;
		}
	}
</style>
