<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { LIMIT_FAAN, POINTS_TABLES } from '$lib/net/protocol.constants';
	import type { RuleSet, ScoreTable } from '$lib/net/ruleset';
	import { patternInfo } from './faan-guide';
	import { faanPatternLabel } from './faan-pattern-labels';

	// null = no table in view: explain every variant instead of the one that applies
	let { rules }: { rules: RuleSet | null } = $props();

	const faanOf = (pattern: string): number => patternInfo(pattern)?.faan ?? 0;
	const LOW_LIMIT = faanOf('字一色');
	const HIGH_LIMIT = faanOf('十三么');

	const TABLES: { id: ScoreTable; label: () => string }[] = [
		{ id: 'full_spicy', label: m.createTableDialog_scoreTableFullSpicy },
		{ id: 'half_spicy', label: m.createTableDialog_scoreTableHalfSpicy }
	];

	let maxFaan = $derived(rules ? rules.faan_cap : LIMIT_FAAN);
	let rows = $derived(Array.from({ length: maxFaan + 1 }, (_, faan) => faan));

	// worked payment example: the table minimum, floored at 3 so the quarter shares stay whole
	let exampleFaan = $derived(Math.max(3, rules?.min_faan ?? 3));
	let examplePoints = $derived(POINTS_TABLES[rules?.score_table ?? 'half_spicy'][exampleFaan]);
	let discardModes = $derived(rules ? [rules.discard_payment] : (['all', 'half'] as const));
</script>

<div class="scoring-view" data-testid="guide-scoring">
	<section aria-labelledby="guide-stack-heading">
		<h3 id="guide-stack-heading">{m.guide_scoringStackHeading()}</h3>
		<ul class="rules">
			<li>
				{m.guide_scoringStackAdds({
					flush: faanPatternLabel('清一色'),
					flushFaan: faanOf('清一色'),
					pungs: faanPatternLabel('對對糊'),
					pungsFaan: faanOf('對對糊'),
					total: faanOf('清一色') + faanOf('對對糊')
				})}
			</li>
			<li>{m.guide_scoringStackWinds()}</li>
			<li>{m.guide_scoringStackReplaces()}</li>
			<li>{m.guide_scoringLimits({ low: LOW_LIMIT, high: HIGH_LIMIT })}</li>
			<li>
				{rules ? m.guide_scoringCapTable({ cap: rules.faan_cap }) : m.guide_scoringCapAny()}
			</li>
			<li>
				{rules ? m.guide_scoringMinTable({ min: rules.min_faan }) : m.guide_scoringMinAny()}
			</li>
		</ul>
	</section>

	<section aria-labelledby="guide-points-heading">
		<h3 id="guide-points-heading">{m.guide_pointsHeading()}</h3>
		<p class="note">{m.guide_pointsNote()}</p>
		<table class="points" data-testid="guide-points-table">
			<thead>
				<tr>
					<th scope="col">{m.guide_pointsFaanColumn()}</th>
					{#each TABLES as table (table.id)}
						<th
							scope="col"
							class:active={rules?.score_table === table.id}
							aria-current={rules?.score_table === table.id ? 'true' : undefined}
						>
							{table.label()}
						</th>
					{/each}
				</tr>
			</thead>
			<tbody>
				{#each rows as faan (faan)}
					<tr class:below={rules !== null && faan < rules.min_faan}>
						<th scope="row">{faan}</th>
						{#each TABLES as table (table.id)}
							<td class:active={rules?.score_table === table.id}>{POINTS_TABLES[table.id][faan]}</td
							>
						{/each}
					</tr>
				{/each}
			</tbody>
		</table>
		{#if rules && rules.min_faan > 0}
			<p class="note">{m.guide_pointsBelowMin({ min: rules.min_faan })}</p>
		{/if}
	</section>

	<section aria-labelledby="guide-payment-heading">
		<h3 id="guide-payment-heading">{m.guide_paymentHeading()}</h3>
		<p class="note">{m.guide_paymentExample({ faan: exampleFaan, points: examplePoints })}</p>
		<dl class="payments">
			<dt>{m.guide_paymentSelfDrawTitle()}</dt>
			<dd>
				{m.guide_paymentSelfDraw({ each: examplePoints / 2, total: (examplePoints * 3) / 2 })}
			</dd>
			{#each discardModes as mode (mode)}
				<dt>
					{mode === 'all'
						? m.createTableDialog_discardPaymentAll()
						: m.createTableDialog_discardPaymentHalf()}
				</dt>
				<dd>
					{mode === 'all'
						? m.guide_paymentDiscardAll({ points: examplePoints })
						: m.guide_paymentDiscardHalf({
								half: examplePoints / 2,
								quarter: examplePoints / 4
							})}
				</dd>
			{/each}
			<dt>{faanPatternLabel('搶槓')}</dt>
			<dd>{m.guide_paymentRobKong()}</dd>
		</dl>
	</section>
</div>

<style lang="scss">
	.scoring-view {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
	}

	section {
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	h3 {
		margin: 0;
		font-size: var(--font-size-base);
		color: var(--color-brass);
	}

	.rules {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding-inline-start: var(--space-5);
		font-size: var(--font-size-sm);
	}

	.note {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.points {
		width: 100%;
		max-width: 24rem;
		border-collapse: collapse;
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;

		th,
		td {
			padding: 2px var(--space-3);
			text-align: end;
			border-bottom: 1px solid color-mix(in srgb, var(--color-border) 60%, transparent);
		}

		th[scope='row'],
		thead th:first-child {
			text-align: start;
		}

		thead th {
			font-weight: 600;
			color: var(--color-text-muted);
		}

		.active {
			color: var(--color-text);
			font-weight: 600;
			background: color-mix(in srgb, var(--color-brass) 12%, transparent);
		}

		.below {
			opacity: 0.45;
		}
	}

	.payments {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: var(--space-2) var(--space-3);
		margin: 0;
		font-size: var(--font-size-sm);

		dt {
			font-weight: 600;
		}

		dd {
			margin: 0;
			color: var(--color-text-muted);
		}
	}
</style>
