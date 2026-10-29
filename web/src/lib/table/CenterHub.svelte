<script lang="ts">
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import type { Seat } from '$lib/game/types';
	import { relativeSeat } from './wind';
	import { seatWind, windWord, WIND_CHAR } from './wind';
	import { m } from '$lib/paraglide/messages.js';

	// the table's own compass: wind/hand/wall/min-faan, plus one wind marker per seat, the
	// acting one glowing and carrying the turn ring when this client knows its duration (§5).
	let {
		prevailing,
		handNo,
		dealer,
		turn,
		you,
		wallCount,
		minFaan,
		turnDurationMs
	}: {
		prevailing: ReturnType<typeof seatWind>;
		handNo: number;
		dealer: Seat;
		turn: Seat;
		you: Seat;
		wallCount: number;
		minFaan: number | null;
		turnDurationMs: number | null;
	} = $props();

	const DIRECTIONS = ['self', 'right', 'across', 'left'] as const;
	type Direction = (typeof DIRECTIONS)[number];

	interface Marker {
		direction: Direction;
		seat: Seat;
		windChar: string;
		windAriaLabel: string;
		isTurn: boolean;
	}

	let markers = $derived.by((): Marker[] =>
		([0, 1, 2, 3] as Seat[]).map((seat) => {
			const direction = DIRECTIONS[relativeSeat(seat, you)];
			const wind = seatWind(seat, dealer);
			return {
				direction,
				seat,
				windChar: WIND_CHAR[wind],
				windAriaLabel: m.centerHub_windMarkerAriaLabel({ wind: windWord(wind) }),
				isTurn: seat === turn
			};
		})
	);
</script>

<div class="center-hub" aria-label={m.centerHub_ariaLabel()}>
	<div class="hub-core">
		<span class="hub-prevailing" aria-hidden="true">{WIND_CHAR[prevailing]}</span>
		<span class="hub-hand">{m.centerHub_handLabel({ n: handNo })}</span>
		<span class="wall-count">{m.centerHub_wallLabel()} <strong>{wallCount}</strong></span>
		{#if minFaan !== null}
			<span class="hub-min-faan">{m.centerHub_minFaanLabel({ n: minFaan })}</span>
		{/if}
	</div>

	{#each markers as marker (marker.seat)}
		<div
			class="hub-marker hub-marker--{marker.direction}"
			class:hub-marker--turn={marker.isTurn}
			aria-label={marker.windAriaLabel}
			title={marker.isTurn ? m.centerHub_turnTitle() : undefined}
		>
			{marker.windChar}
			{#if marker.isTurn && turnDurationMs !== null}
				{#key turn}
					<div class="hub-marker-ring"><TimerRing durationMs={turnDurationMs} size={28} /></div>
				{/key}
			{/if}
		</div>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	// markers straddle the rim half inside it; the padding is that band, so no label runs under one.
	// a pill, not a stacked circle: the centre box's height is what runs out (docs/frontend.md §3).
	.center-hub {
		--hub-marker: 1.5rem;
		position: relative;
		display: flex;
		align-items: center;
		justify-content: center;
		width: max-content;
		padding: calc(var(--hub-marker) / 2 + 2px) calc(var(--hub-marker) / 2 + var(--space-2));
		margin: var(--space-2) auto;
		border-radius: var(--radius-pill);
		border: 1px solid var(--color-felt-line);
		background: rgb(0 0 0 / 0.12);
		text-align: center;
		color: var(--color-text-on-felt, var(--color-text));
	}

	.hub-core {
		display: grid;
		grid-auto-flow: column;
		grid-template-rows: repeat(3, auto);
		align-items: center;
		justify-items: start;
		gap: 1px var(--space-2);
		font-size: var(--font-size-xs);
		line-height: 1.25;
		white-space: nowrap;
		color: var(--color-text-muted);
	}

	.hub-prevailing {
		grid-row: span 3;
		font-size: var(--font-size-xl);
		font-weight: 700;
		line-height: 1;
		color: var(--color-text);
	}

	.wall-count strong,
	.hub-hand {
		font-variant-numeric: tabular-nums;
	}

	.hub-min-faan {
		padding: 0 var(--space-1);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}

	// the four wind markers sit outside the circle, toward each seat -- absolutely positioned so
	// they never affect the hub's own (or the grid's) layout.
	.hub-marker {
		position: absolute;
		display: flex;
		align-items: center;
		justify-content: center;
		width: var(--hub-marker);
		height: var(--hub-marker);
		border-radius: 50%;
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border);
		font-size: var(--font-size-sm);
		font-weight: 700;
	}

	.hub-marker--across {
		top: calc(var(--hub-marker) / -2);
		left: 50%;
		translate: -50% 0;
	}

	.hub-marker--self {
		bottom: calc(var(--hub-marker) / -2);
		left: 50%;
		translate: -50% 0;
	}

	.hub-marker--left {
		left: calc(var(--hub-marker) / -2);
		top: 50%;
		translate: 0 -50%;
	}

	.hub-marker--right {
		right: calc(var(--hub-marker) / -2);
		top: 50%;
		translate: 0 -50%;
	}

	.hub-marker--turn {
		border-color: var(--color-accent);
		box-shadow: 0 0 0 3px var(--color-accent-glow);

		@include a11y.motion-ok {
			animation: hub-marker-pulse 1.8s ease-in-out infinite;
		}
	}

	@keyframes hub-marker-pulse {
		50% {
			opacity: 0.6;
		}
	}

	.hub-marker-ring {
		position: absolute;
		inset: -2px;
		pointer-events: none;
	}

	// below tablet-up the pools stack instead of forming a box (§3): no room for markers outside
	// the hub without overlapping one, so they drop and the hub becomes a summary row.
	@include layout.phone-only {
		.center-hub {
			flex-direction: row;
			justify-content: center;
			gap: var(--space-3);
			width: 100%;
			padding: var(--space-1) var(--space-2);
			border-radius: var(--radius-md);
		}

		.hub-core {
			display: flex;
			flex-direction: row;
			align-items: center;
			gap: var(--space-2);
			line-height: inherit;
			white-space: normal;
		}

		.hub-prevailing {
			font-size: var(--font-size-lg);
			line-height: inherit;
		}

		.hub-marker {
			display: none;
		}
	}
</style>
