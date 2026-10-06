<script lang="ts">
	import type { Snippet } from 'svelte';

	// shared seat header: name, wind, dealer badge, an extra-badges slot, and the score.
	// `isTurn`'s halo is a pseudo-element overlay so it never shifts the header's own layout.
	let {
		name,
		windChar,
		windAriaLabel,
		isDealer,
		dealerTitle,
		score,
		isTurn = false,
		badges
	}: {
		name: string;
		windChar: string;
		windAriaLabel: string;
		isDealer: boolean;
		dealerTitle: string;
		score: number;
		isTurn?: boolean;
		badges?: Snippet;
	} = $props();
</script>

<div class="seat-plate" class:seat-plate--turn={isTurn}>
	<span class="seat-name">{name}</span>
	<span class="seat-wind" aria-label={windAriaLabel}>{windChar}</span>
	{#if isDealer}<span class="dealer-badge" title={dealerTitle}>莊</span>{/if}
	{@render badges?.()}
	<span class="seat-score">{score}</span>
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/tile';

	.seat-plate {
		position: relative;
		@include tile.seat-meta;
	}

	.seat-name {
		@include tile.seat-name;
	}

	.seat-wind {
		@include tile.seat-wind;
	}

	.dealer-badge {
		@include tile.dealer-badge;
	}

	.seat-score {
		@include tile.seat-score;
	}

	// absolutely-positioned halo, not a border/outline on .seat-plate itself -- inset sits outside
	// the box so the plate's own size (and the header row's layout) never changes between turns.
	.seat-plate--turn::before {
		content: '';
		position: absolute;
		inset: -0.35rem -0.5rem;
		border: 2px solid var(--color-accent);
		border-radius: var(--radius-md);
		box-shadow: 0 0 0 4px var(--color-accent-glow);
		pointer-events: none;

		@include a11y.motion-ok {
			animation: seat-plate-pulse 1.8s ease-in-out infinite;
		}
	}

	@keyframes seat-plate-pulse {
		50% {
			opacity: 0.55;
		}
	}
</style>
