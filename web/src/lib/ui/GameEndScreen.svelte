<script lang="ts">
	// Auto-shown once a real `game_end` lands (docs/03-frontend.md §6/`/table/[id]` wiring) --
	// unlike the per-hand hold-and-ack overlay, this isn't dismissable back into play: the game
	// is genuinely over, there's no next hand to advance into. Reuses `ScoreSheet` wholesale
	// (score table + standings + this sub-task's expandable per-round detail) rather than a
	// second table/markup implementation -- this component only adds the "game over" framing and
	// a way back out of the now-terminal table route.
	import ScoreSheet, {
		type HandRecord,
		type SeatInfo,
		type Standing,
		type Totals
	} from './ScoreSheet.svelte';

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

	const RANK_LABEL = ['1st', '2nd', '3rd', '4th'];
	const RANK_TONE: Record<number, string> = {
		0: '#d4af37',
		1: '#a8a8a8',
		2: '#cd7f32'
	};

	function seatName(seat: 0 | 1 | 2 | 3): string {
		return seats.find((s) => s.seat === seat)?.name ?? `Seat ${seat}`;
	}
</script>

<section class="game-end" aria-labelledby="game-end-heading">
	<header class="game-end-header">
		<h1 id="game-end-heading">Game over</h1>
		<p class="game-end-subtitle">Thanks for playing</p>
	</header>

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

	<ScoreSheet {seats} {totals} {hands} {standings} />
	<a class="home-link" href="/">Back to home</a>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';
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
		flex-direction: column;
		align-items: center;
		gap: var(--space-1);
		text-align: center;
	}

	h1 {
		margin: 0;
		font-size: clamp(2.5rem, 8vw, 4rem);
		font-weight: 900;
		letter-spacing: -0.04em;
		line-height: 1;
	}

	.game-end-subtitle {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-lg);
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
		background: rgb(255 255 255 / 0.05);
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

	.home-link {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-width: 12rem;
		padding: var(--space-3) var(--space-6);
		text-align: center;
		text-decoration: none;
		font-size: var(--font-size-lg);
		font-weight: 700;
		@include buttons.btn-primary;
	}
</style>
