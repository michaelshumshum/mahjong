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
</script>

<section class="game-end" aria-labelledby="game-end-heading">
	<h1 id="game-end-heading">Game over</h1>
	<ScoreSheet {seats} {totals} {hands} {standings} />
	<a class="home-link" href="/">Back to home</a>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.game-end {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		max-height: 90vh;
		overflow-y: auto;
	}

	h1 {
		margin: 0;
		font-size: var(--font-size-xl);
	}

	.home-link {
		display: inline-block;
		padding: var(--space-2) var(--space-4);
		text-align: center;
		text-decoration: none;
		@include buttons.btn-primary;
	}
</style>
