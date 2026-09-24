<script lang="ts">
	// Auto-shown once a real `game_end` lands -- unlike the per-hand hold overlay, not
	// dismissable back into play. Reuses ScoreSheet wholesale, adding only "game over" framing.
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from './ScoreSheet.svelte';
	import BackButton from './BackButton.svelte';
	import { RANK_LABEL, RANK_TONE } from './rank';

	let {
		seats,
		totals,
		hands,
		standings
	}: {
		seats: SeatInfo[];
		totals: Totals;
		hands: HandRecord[];
		standings: Standing[];
	} = $props();

	function seatName(seat: 0 | 1 | 2 | 3): string {
		return seats.find((s) => s.seat === seat)?.name ?? `Seat ${seat}`;
	}
</script>

<section class="game-end" aria-label="Game end summary">
	<div class="game-end-header">
		<BackButton label="Back to home" href="/" />
	</div>
	<div class="podium">
		{#each standings.slice(0, 3) as standing, index (standing.seat)}
			{@const rank = index}
			<div
				class="podium-step"
				class:podium-step--first={rank === 0}
				style:--step-color={RANK_TONE[rank]}
			>
				<span class="podium-rank">{RANK_LABEL[rank]}</span>
				<span class="podium-name">{seatName(standing.seat)}</span>
				<span
					class="podium-score"
					class:podium-score--positive={standing.total > 0}
					class:podium-score--negative={standing.total < 0}
				>
					{standing.total > 0 ? '+' : ''}{standing.total}
				</span>
			</div>
		{/each}
	</div>

	<ScoreSheet {seats} {totals} {hands} />
</section>

<style lang="scss">
	@use '$lib/styles/layout';

	.game-end {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-5);
		padding: var(--space-4);

		@include layout.tablet-up {
			padding: var(--space-6);
		}
	}

	.game-end-header {
		display: flex;
		align-self: flex-start;
	}

	.podium {
		display: flex;
		align-items: flex-end;
		justify-content: center;
		gap: var(--space-3);
		width: 100%;
		max-width: 40rem;
	}

	.podium-step {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
		padding: var(--space-4) var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md) var(--radius-md) 0 0;
		background: var(--color-surface-raised);
		border-top: 4px solid var(--step-color, var(--color-border));
		text-align: center;

		&:nth-child(1) {
			order: 2;
			padding-block: var(--space-6);
		}
		&:nth-child(2) {
			order: 1;
		}
		&:nth-child(3) {
			order: 3;
		}
	}

	.podium-step--first {
		background: #3d3120;
		box-shadow: 0 -8px 24px -4px rgb(212 175 55 / 0.15);
	}

	.podium-rank {
		font-size: var(--font-size-lg);
		font-weight: 800;
		color: var(--step-color, var(--color-text-muted));
	}

	.podium-name {
		font-size: var(--font-size-lg);
		font-weight: 700;
	}

	.podium-score {
		font-size: var(--font-size-xl);
		font-weight: 800;
	}

	.podium-score--positive {
		color: var(--color-accent-jade);
	}

	.podium-score--negative {
		color: var(--color-accent);
	}
</style>
