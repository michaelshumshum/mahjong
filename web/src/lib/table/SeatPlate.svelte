<script lang="ts">
	import type { Snippet } from 'svelte';

	// shared seat header; `isTurn`'s halo never shifts the layout (pseudo-element overlay).
	// `sealStamp`/`scoreDelta` are the same kind of transient overlay, keyed to replay on repeat.
	let {
		name,
		windChar,
		windAriaLabel,
		isDealer,
		dealerTitle,
		score,
		isTurn = false,
		sealStamp = null,
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
		sealStamp?: { glyph: string; key: number } | null;
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
	{#if sealStamp}
		{#key sealStamp.key}
			<span class="seal-stamp" aria-hidden="true">{sealStamp.glyph}</span>
		{/key}
	{/if}
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

	// claim "seal stamp": the call glyph briefly presses over the plate -- caller never sets
	// it under reduced motion (same for the score-delta chip below).
	.seal-stamp {
		position: absolute;
		inset: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: var(--font-size-2xl);
		font-weight: 700;
		color: var(--color-accent);
		background: rgb(0 0 0 / 0.25);
		border-radius: var(--radius-md);
		pointer-events: none;
		opacity: 0;
		animation: seal-stamp var(--dur-4) var(--ease-place) forwards;
	}

	@keyframes seal-stamp {
		0% {
			opacity: 0;
			scale: 1.4;
			rotate: -8deg;
		}
		25% {
			opacity: 1;
			scale: 1;
			rotate: 3deg;
		}
		70% {
			opacity: 1;
			scale: 1;
			rotate: 0deg;
		}
		100% {
			opacity: 0;
			scale: 1;
			rotate: 0deg;
		}
	}

	// score-delta chip: floats up and fades once, near the plate, on hand end.
	.score-delta {
		position: absolute;
		top: -1.4rem;
		left: 50%;
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
