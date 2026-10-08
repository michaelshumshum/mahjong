<script lang="ts">
	let { label, self = false }: { label: string; self?: boolean } = $props();
</script>

<div class="seat-ring-slot" class:seat-ring-slot--self={self}>
	<span>{label}</span>
</div>

<style lang="scss">
	// your own seat reads as plain accent text -- the felt's wind glyphs already frame the ring,
	// so a second badge around the wind char would just echo it.
	.seat-ring-slot {
		color: var(--color-text-muted);
		font-size: var(--font-size-lg);
		font-weight: 700;

		span {
			overflow: hidden;
			text-overflow: ellipsis;
			user-select: none;
		}
	}

	// dealer is fixed at table creation, so once seated your own wind is true, not a guess.
	.seat-ring-slot--self {
		color: var(--color-text);
	}
</style>
