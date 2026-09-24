<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import type { TileCode } from '../table/tile-code';

	export type Seat = 0 | 1 | 2 | 3;

	// mirrors melds.MeldKind, minus PAIR -- kept local since this only needs kind/tiles.
	export type MeldKind = 'chow' | 'pung' | 'exposed_kong' | 'concealed_kong' | 'added_kong';

	export interface WinningMeld {
		kind: MeldKind;
		tiles: TileCode[];
	}

	export interface FaanPattern {
		name: string;
		faan: number;
	}

	let {
		winningHand,
		melds = [],
		patterns,
		totalFaan
	}: {
		winningHand: TileCode[];
		melds?: WinningMeld[];
		patterns: FaanPattern[];
		totalFaan: number;
	} = $props();

	// reading order within a suit (docs/01-rules-spec.md §1's index layout: m, p, s, then honors).
	const SUIT_ORDER: Record<string, number> = { m: 0, p: 1, s: 2 };
	function tileSortKey(code: TileCode): number {
		return code[0] === 'z'
			? 30 + Number(code[1])
			: (SUIT_ORDER[code[1]] ?? 9) * 9 + Number(code[0]);
	}
	function sortTiles(tiles: TileCode[]): TileCode[] {
		return tiles.slice().sort((a, b) => tileSortKey(a) - tileSortKey(b));
	}

	let sortedMelds = $derived(
		melds
			.map((meld) => ({ ...meld, tiles: sortTiles(meld.tiles) }))
			.sort((a, b) => tileSortKey(a.tiles[0]) - tileSortKey(b.tiles[0]))
	);
	let sortedConcealedHand = $derived(sortTiles(winningHand));

	let patternSum = $derived(patterns.reduce((sum, p) => sum + p.faan, 0));
	let isCapped = $derived(patternSum > totalFaan);
</script>

<section class="winning-hand-summary" aria-label="Winning hand and faan">
	{#if sortedMelds.length > 0 || sortedConcealedHand.length > 0}
		<div class="hand">
			{#if sortedMelds.length > 0}
				<div class="melds">
					{#each sortedMelds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (`${mi}:${ti}:${code}`)}
								<div class="tile">
									<TileFace code={meld.kind === 'concealed_kong' ? null : code} />
								</div>
							{/each}
						</div>
					{/each}
				</div>
			{/if}
			{#if sortedConcealedHand.length > 0}
				<div class="concealed-hand">
					{#each sortedConcealedHand as code, index (`${index}:${code}`)}
						<div class="tile"><TileFace {code} /></div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}

	<ul class="patterns">
		{#each patterns as pattern, index (`${index}:${pattern.name}`)}
			<li class="pattern-row">
				<span class="pattern-name">{pattern.name}</span>
				<span class="pattern-faan">{pattern.faan} faan</span>
			</li>
		{/each}
	</ul>

	<p class="total" class:total--capped={isCapped}>
		Total <strong>{totalFaan} faan</strong>
		{#if isCapped}
			<span class="cap-note">(capped from {patternSum})</span>
		{/if}
	</p>
</section>

<style lang="scss">
	.winning-hand-summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.hand {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.melds,
	.concealed-hand {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
	}

	.meld {
		display: flex;
		gap: 2px;
	}

	.tile :global(.tile-face) {
		height: 32px;
	}

	.patterns {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr));
		gap: var(--space-1) var(--space-3);
	}

	.pattern-row {
		display: flex;
		justify-content: space-between;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.pattern-faan {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.total {
		margin: 0;
		padding-block-start: var(--space-2);
		border-top: 1px solid var(--color-border);
		font-size: var(--font-size-base);
		font-variant-numeric: tabular-nums;
	}

	.cap-note {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}
</style>
