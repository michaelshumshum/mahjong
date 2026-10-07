<script lang="ts">
	import type { Snippet } from 'svelte';

	// shared seat header; `isTurn`'s halo never shifts the layout (pseudo-element overlay).
	// `scoreDelta` is the same kind of transient overlay, keyed to replay on repeat.
	let {
		name,
		windChar,
		windAriaLabel,
		isDealer,
		dealerTitle,
		score,
		isTurn = false,
		scoreDelta = null,
		badges
	}: {
		name: string;
		windChar: string;
		windAriaLabel: string;
		isDealer: boolean;
		dealerTitle: string;
		score: number;
		isTurn?: boolean;
		scoreDelta?: { value: number; key: number } | null;
		badges?: Snippet;
	} = $props();
</script>

<div class="seat-plate" class:seat-plate--turn={isTurn}>
	<span class="seat-name">{name}</span>
	<span class="seat-wind" aria-label={windAriaLabel}>{windChar}</span>
	{#if isDealer}<span class="dealer-badge" title={dealerTitle}>莊</span>{/if}
	{@render badges?.()}
	<span class="seat-score">{score}</span>
	{#if scoreDelta}
		{#key scoreDelta.key}
			<span
				class="score-delta"
				class:score-delta--negative={scoreDelta.value < 0}
				aria-hidden="true"
			>
				{scoreDelta.value > 0 ? `+${scoreDelta.value}` : scoreDelta.value}
			</span>
		{/key}
	{/if}
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

	// score-delta chip: floats up and fades once, near the plate, on hand end.
	.score-delta {
		position: absolute;
		top: -1.4rem;
		left: 50%;
		padding: 0 var(--space-1);
		border-radius: var(--radius-sm);
		// a dark pill: bare delta colours on lit felt are under 4:1.
		background: rgb(0 0 0 / 0.55);
		font-size: var(--font-size-sm);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--color-positive);
		pointer-events: none;
		opacity: 0;
		animation: score-delta-float var(--dur-4) var(--ease-out) forwards;
	}

	.score-delta--negative {
		color: var(--color-negative);
	}

	@keyframes score-delta-float {
		0% {
			opacity: 0;
			translate: -50% 4px;
		}
		20% {
			opacity: 1;
			translate: -50% 0;
		}
		75% {
			opacity: 1;
			translate: -50% 0;
		}
		100% {
			opacity: 0;
			translate: -50% -16px;
		}
	}
</style>
