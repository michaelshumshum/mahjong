<script lang="ts">
	let { name, size = 'sm' }: { name: string; size?: 'sm' | 'lg' } = $props();

	const initial = $derived(([...name.trim()][0] ?? '?').toUpperCase());
</script>

<!-- the seal's ink-red, so it reads as the player's own stamp -->
<span class="avatar avatar--{size}" aria-hidden="true">{initial}</span>

<style lang="scss">
	.avatar {
		display: grid;
		flex: none;
		place-items: center;
		border-radius: var(--radius-pill);
		background: var(--color-accent);
		color: var(--color-text);
		font-weight: 700;
		line-height: 1;
	}

	.avatar--sm {
		width: 1.75rem;
		height: 1.75rem;
		font-size: var(--font-size-sm);
	}

	.avatar--lg {
		width: 2.75rem;
		height: 2.75rem;
		font-size: var(--font-size-lg);
	}
</style>
