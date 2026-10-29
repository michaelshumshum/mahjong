<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import type { TileCode } from '$lib/table/tile-code';
	import TileFace from '$lib/table/TileFace.svelte';
	import type { OptionTableRow } from './types';

	// the first column is the tile; `columns` names it and every cell after it.
	let {
		caption,
		columns,
		numeric = [],
		rows,
		testid
	}: {
		caption: string;
		columns: readonly string[];
		// indexes into `columns` that hold numbers, right-aligned
		numeric?: readonly number[];
		rows: readonly OptionTableRow[];
		testid: string;
	} = $props();
</script>

<table class="option-table" data-testid={testid}>
	<caption>{caption}</caption>
	<thead>
		<tr>
			{#each columns as column, i (i)}
				<th scope="col" class:num={numeric.includes(i)}>{column}</th>
			{/each}
		</tr>
	</thead>
	<tbody>
		{#each rows as row (row.tile)}
			<tr
				class="row--{row.tone}"
				class:row--picked={row.picked}
				data-tile={row.tile}
				data-answer={row.answer}
				data-picked={row.picked}
			>
				<th scope="row">
					<span class="tile-cell">
						<span class="tile"><TileFace code={row.tile as TileCode} /></span>
						{#if row.answer}<span class="mark mark--answer">{m.learn_answerMark()}</span>{/if}
						{#if row.picked}<span class="mark mark--pick">{m.learn_pickMark()}</span>{/if}
					</span>
				</th>
				{#each row.cells as cell, i (i)}
					<td class:num={numeric.includes(i + 1)}>{cell}</td>
				{/each}
			</tr>
		{/each}
	</tbody>
</table>

<style lang="scss">
	.option-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--font-size-sm);
	}

	caption {
		margin-bottom: var(--space-2);
		text-align: start;
		color: var(--color-text-muted);
	}

	th,
	td {
		padding: var(--space-1) var(--space-2);
		text-align: start;
		vertical-align: middle;
	}

	thead th {
		font-weight: 600;
		color: var(--color-text-muted);
		border-bottom: 1px solid var(--color-border);
	}

	tbody tr {
		border-bottom: 1px dashed color-mix(in srgb, var(--color-border) 70%, transparent);
	}

	tbody th {
		font-weight: 400;
	}

	.num {
		text-align: end;
		font-variant-numeric: tabular-nums;
	}

	.tile-cell {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
	}

	.tile {
		display: inline-flex;
		height: 2rem;
	}

	.mark {
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 700;
		white-space: nowrap;
	}

	.mark--answer {
		color: var(--color-positive);
		background: color-mix(in srgb, var(--color-positive) 16%, transparent);
	}

	.mark--pick {
		color: var(--color-brass);
		border: 1px solid var(--color-brass);
	}

	.row--good {
		background: color-mix(in srgb, var(--color-positive) 8%, transparent);
	}

	.row--bad td {
		color: var(--color-negative);
	}

	// inset, so the row's own box (and the column widths) never change
	.row--picked {
		box-shadow: inset 3px 0 0 var(--color-brass);
	}
</style>
