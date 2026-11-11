<script lang="ts">
	let {
		name,
		src = null,
		size = 'sm'
	}: { name: string; src?: string | null; size?: 'sm' | 'lg' } = $props();

	const initial = $derived(([...name.trim()][0] ?? '?').toUpperCase());
	let failed = $state<string | null>(null);
	const showImage = $derived(src !== null && src !== failed);
</script>

<!-- the seal's ink-red, so it reads as the player's own stamp; the initial stays under a picture
     that fails to load. no-referrer: google's image host never learns which page showed it -->
<span class="avatar avatar--{size}" aria-hidden="true">
	{#if showImage}
		<img {src} alt="" referrerpolicy="no-referrer" onerror={() => (failed = src)} />
	{:else}
		{initial}
	{/if}
</span>

<style lang="scss">
	.avatar {
		display: grid;
		flex: none;
		place-items: center;
		overflow: hidden;
		border-radius: var(--radius-pill);
		background: var(--color-accent);
		color: var(--color-text);
		font-weight: 700;
		line-height: 1;

		img {
			width: 100%;
			height: 100%;
			object-fit: cover;
		}
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
