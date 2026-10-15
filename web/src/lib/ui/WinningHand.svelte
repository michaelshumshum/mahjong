<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import { meldTileFace, sortMelds } from '../table/meld-face';
	import { sortTiles, type TileCode } from '../table/tile-code';
	import type { FaanPattern, WinningMeld } from '$lib/game/types';
	import { m } from '$lib/paraglide/messages.js';

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

	let sortedMelds = $derived(sortMelds(melds));
	let sortedConcealedHand = $derived(sortTiles(winningHand));

	let patternSum = $derived(patterns.reduce((sum, p) => sum + p.faan, 0));
	let isCapped = $derived(patternSum > totalFaan);
</script>

<section class="winning-hand-summary" aria-label={m.winningHand_ariaLabel()}>
	{#if sortedMelds.length > 0 || sortedConcealedHand.length > 0}
		<div class="hand">
			{#if sortedMelds.length > 0}
				<div class="melds">
					{#each sortedMelds as meld, mi (mi)}
						<div class="meld">
							{#each meld.tiles as code, ti (`${mi}:${ti}:${code}`)}
								<div class="tile">
									<TileFace code={meldTileFace(meld.kind, code, ti, meld.tiles.length)} />
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
				<span class="pattern-faan">{m.winningHand_faanCountLabel({ faan: pattern.faan })}</span>
			</li>
		{/each}
	</ul>

	<p class="total" class:total--capped={isCapped}>
		{m.winningHand_totalLabel()}
		<strong>{m.winningHand_faanCountLabel({ faan: totalFaan })}</strong>
		{#if isCapped}
			<span class="cap-note">{m.winningHand_cappedFromLabel({ sum: patternSum })}</span>
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
