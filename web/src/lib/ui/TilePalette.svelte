<script lang="ts">
	import TileFace from '$lib/table/TileFace.svelte';
	import type { TileCode } from '$lib/table/tile-code';

	const SUITS = ['m', 'p', 's'] as const;
	const RANKS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;
	const HONORS: TileCode[] = ['z1', 'z2', 'z3', 'z4', 'z5', 'z6', 'z7'];
	const FLOWERS: TileCode[] = ['f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8'];

	// tile height is the caller's `--palette-tile-h` (default 2.25rem).
	let {
		label,
		tileLabel,
		onPick,
		canPick = () => true,
		selected,
		flowers = true,
		testidPrefix
	}: {
		label: string;
		tileLabel: (code: TileCode) => string;
		onPick: (code: TileCode) => void;
		canPick?: (code: TileCode) => boolean;
		// given, each tile is a toggle (aria-pressed) and the selected ones are outlined
		selected?: ReadonlySet<TileCode>;
		flowers?: boolean;
		testidPrefix?: string;
	} = $props();

	let rows = $derived<TileCode[][]>([
		...SUITS.map((suit) => RANKS.map((rank) => `${rank}${suit}` as TileCode)),
		HONORS,
		...(flowers ? [FLOWERS] : [])
	]);
</script>

<div class="tile-palette" role="group" aria-label={label}>
	{#each rows as row, r (r)}
		<div class="palette-row">
			{#each row as code (code)}
				<button
					type="button"
					class="tile-btn"
					class:tile-btn--selected={selected?.has(code)}
					disabled={!canPick(code)}
					aria-label={tileLabel(code)}
					aria-pressed={selected ? selected.has(code) : undefined}
					data-testid={testidPrefix ? `${testidPrefix}${code}` : undefined}
					onclick={() => onPick(code)}><TileFace {code} /></button
				>
			{/each}
		</div>
	{/each}
</div>

<style lang="scss">
	.tile-palette {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.palette-row {
		display: flex;
		flex-wrap: wrap;
		gap: 2px;
	}

	.tile-btn {
		display: inline-block;
		height: var(--palette-tile-h, 2.25rem);
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;

		&:disabled {
			cursor: default;
			opacity: 0.3;
		}
	}

	.tile-btn--selected {
		border-radius: var(--radius-sm);
		box-shadow: 0 0 0 2px var(--color-brass);
	}
</style>
