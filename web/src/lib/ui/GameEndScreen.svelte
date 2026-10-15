<script lang="ts">
	// Auto-shown once a real `game_end` lands -- unlike the per-hand hold overlay, not
	// dismissable back into play. Final standings first, then the full ScoreSheet.
	import ScoreSheet from './ScoreSheet.svelte';
	import type { HandRecord, SeatInfo, Standing, Totals } from '$lib/game/types';
	import { placements, rankLabel, RANK_TONE } from './rank';
	import { m } from '$lib/paraglide/messages.js';

	let {
		seats,
		totals,
		hands,
		standings,
		you = null,
		onPlayAgain,
		playAgainPending = false,
		playAgainFailed = false
	}: {
		seats: SeatInfo[];
		totals: Totals;
		hands: HandRecord[];
		standings: Standing[];
		// null for a spectator -- no "you placed" line, no highlighted row.
		you?: 0 | 1 | 2 | 3 | null;
		// practice tables only: re-creates one with the same bot levels.
		onPlayAgain?: () => void;
		playAgainPending?: boolean;
		playAgainFailed?: boolean;
	} = $props();

	function seatName(seat: 0 | 1 | 2 | 3): string {
		return seats.find((s) => s.seat === seat)?.name ?? m.gameEndScreen_seatFallbackLabel({ seat });
	}

	let places = $derived(placements(standings.map((s) => s.total)));
	let rows = $derived(
		standings.map((standing, i) => ({
			...standing,
			place: places[i],
			tied: places.filter((p) => p === places[i]).length > 1
		}))
	);
	let yourRow = $derived(you === null ? undefined : rows.find((r) => r.seat === you));
</script>

<section class="game-end" aria-labelledby="game-end-heading">
	<header class="game-end-header">
		<h2 id="game-end-heading">{m.gameEndScreen_heading()}</h2>
		{#if yourRow}
			<p class="you-placed" data-testid="game-end-you-placed">
				{yourRow.tied
					? m.gameEndScreen_youTied({ rank: rankLabel(yourRow.place) })
					: m.gameEndScreen_youPlaced({ rank: rankLabel(yourRow.place) })}
			</p>
		{/if}
	</header>

	<ol class="final-standings" data-testid="game-end-standings">
		{#each rows as row, i (row.seat)}
			<li
				class="final-row"
				class:final-row--first={row.place === 0}
				class:final-row--you={row.seat === you}
				style:--rank-tone={RANK_TONE[row.place] ?? 'var(--color-border)'}
				style:--i={i}
			>
				<span class="final-rank">{rankLabel(row.place)}</span>
				<span class="final-name">
					{seatName(row.seat)}
					{#if row.seat === you}<span class="sr-only">{m.gameEndScreen_youTag()}</span>{/if}
					{#if row.tied}<span class="tied-tag">{m.gameEndScreen_tiedTag()}</span>{/if}
				</span>
				<span
					class="final-total"
					class:final-total--positive={row.total > 0}
					class:final-total--negative={row.total < 0}
				>
					{row.total > 0 ? '+' : ''}{row.total}
				</span>
			</li>
		{/each}
	</ol>

	<div class="game-end-actions">
		{#if onPlayAgain}
			<button
				type="button"
				class="action action--primary"
				data-testid="game-end-play-again"
				disabled={playAgainPending}
				onclick={onPlayAgain}
			>
				{playAgainPending ? m.gameEndScreen_playAgainPending() : m.gameEndScreen_playAgainButton()}
			</button>
		{/if}
		<a
			class="action"
			class:action--primary={!onPlayAgain}
			class:action--secondary={!!onPlayAgain}
			href="/">{m.gameEndScreen_backToHomeLabel()}</a
		>
	</div>
	{#if playAgainFailed}
		<p class="play-again-error" role="alert">{m.gameEndScreen_playAgainError()}</p>
	{/if}

	<div class="score-sheet-wrap">
		<h3 class="score-sheet-heading">{m.gameEndScreen_scoreSheetSummary()}</h3>
		<ScoreSheet {seats} {totals} {hands} />
	</div>
</section>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.game-end {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-5);
		width: min(60rem, 100%);
		margin-inline: auto;
		padding: var(--space-5) var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6);
		}
	}

	.game-end-header {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		text-align: center;

		h2 {
			margin: 0;
			font-size: var(--font-size-2xl);
			line-height: 1;
			letter-spacing: -0.02em;
		}
	}

	.you-placed {
		margin: 0;
		color: var(--color-brass);
		font-size: var(--font-size-lg);
		font-weight: 700;
	}

	.final-standings {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: 100%;
		max-width: 30rem;
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.final-row {
		display: grid;
		grid-template-columns: 4.5rem minmax(0, 1fr) auto;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-4) var(--space-2) var(--space-2);
		border: 1px solid var(--color-border);
		border-left: 4px solid var(--rank-tone);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		font-variant-numeric: tabular-nums;

		@include a11y.motion-ok {
			animation: row-in var(--dur-3) var(--ease-out) both;
			animation-delay: calc(var(--dur-2) + var(--i) * 110ms);
		}
	}

	@keyframes row-in {
		from {
			opacity: 0;
			transform: translateY(10px);
		}
	}

	.final-row--first {
		padding-block: var(--space-3);
		background: color-mix(in srgb, var(--color-rank-gold) 10%, var(--color-surface));
	}

	.final-row--you {
		outline: 2px solid color-mix(in srgb, var(--color-brass) 70%, transparent);
		outline-offset: 1px;
	}

	.final-rank {
		justify-self: start;
		padding: 2px var(--space-2);
		border-radius: var(--radius-pill);
		background: var(--rank-tone);
		color: var(--color-tile-ink);
		font-size: var(--font-size-sm);
		font-weight: 800;
	}

	.final-name {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-width: 0;
		overflow: hidden;
		font-size: var(--font-size-lg);
		font-weight: 700;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.tied-tag {
		flex: none;
		padding: 1px var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-pill);
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.final-total {
		font-size: var(--font-size-xl);
		font-weight: 800;
	}

	.final-row:not(.final-row--first) .final-total {
		font-size: var(--font-size-lg);
	}

	.final-total--positive {
		color: var(--color-positive);
	}

	.final-total--negative {
		color: var(--color-negative);
	}

	.game-end-actions {
		display: flex;
		flex-wrap: wrap;
		justify-content: center;
		gap: var(--space-3);
		width: 100%;
		max-width: 30rem;
	}

	.action {
		flex: 1 1 10rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		@include buttons.btn-base(var(--space-5));
		text-decoration: none;
	}

	.action--primary {
		@include buttons.btn-primary;
	}

	.action--secondary {
		@include buttons.btn-secondary;
	}

	.play-again-error {
		margin: 0;
		color: var(--color-status-error);
		font-size: var(--font-size-sm);
	}

	.score-sheet-wrap {
		min-width: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		width: 100%;
		max-width: 56rem;
	}

	.score-sheet-heading {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	// phone landscape: result and actions on the left, the score sheet scrolling on its own on the
	// right, so Play again is in view without scrolling the dialog.
	@include layout.phone-landscape {
		.game-end {
			display: grid;
			grid-template-areas:
				'header sheet'
				'standings sheet'
				'actions sheet'
				'error sheet';
			grid-template-columns: minmax(0, 20rem) minmax(0, 1fr);
			grid-template-rows: auto auto auto 1fr;
			align-items: start;
			gap: var(--space-3) var(--space-5);
			width: 100%;
			max-width: none;
			height: calc(100dvh - 2 * var(--space-3));
			padding: var(--space-3) var(--space-4);
		}

		.game-end-header {
			grid-area: header;

			h2 {
				font-size: var(--font-size-xl);
			}
		}

		.you-placed {
			font-size: var(--font-size-base);
		}

		.final-standings {
			grid-area: standings;
			gap: var(--space-1);
		}

		.final-row,
		.final-row--first {
			padding-block: var(--space-1);
		}

		.final-name,
		.final-total,
		.final-row:not(.final-row--first) .final-total {
			font-size: var(--font-size-base);
		}

		.game-end-actions {
			grid-area: actions;
			flex-wrap: nowrap;
		}

		.action {
			flex-basis: 0;
			padding-inline: var(--space-3);
		}

		.play-again-error {
			grid-area: error;
		}

		.score-sheet-wrap {
			grid-area: sheet;
			align-self: stretch;
			min-height: 0;
			overflow-y: auto;
		}
	}
</style>
