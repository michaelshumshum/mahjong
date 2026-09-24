<script lang="ts">
	import TileFace from '$lib/table/TileFace.svelte';
	import type { TileCode } from '$lib/table/tile-code';

	// proves TileFace renders vendored art per code plus a back for concealed codes.
	const demoCodes: (TileCode | null)[] = ['1m', '9m', '5p', '1s', 'z1', 'z5', 'z7', 'f1', null];
</script>

<h2>TileFace demo</h2>
<div class="tile-row">
	{#each demoCodes as code (code)}
		<figure>
			<TileFace {code} />
			<figcaption>{code ?? 'back'}</figcaption>
		</figure>
	{/each}
</div>

<style lang="scss">
	.tile-row {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	figure {
		margin: 0;
		text-align: center;
	}

	figure :global(.tile-face) {
		height: 88px;
	}
</style>
