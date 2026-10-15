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

	.center-hub {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		width: clamp(84px, 11cqi, 128px);
		height: clamp(84px, 11cqi, 128px);
		margin: var(--space-2) auto;
		border-radius: 50%;
		border: 1px solid var(--color-felt-line);
		background: rgb(0 0 0 / 0.12);
		text-align: center;
		color: var(--color-text-on-felt, var(--color-text));
	}

	.hub-core {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1px;
		font-size: var(--font-size-xs);
		color: var(--color-text-muted);
	}

	.hub-prevailing {
		font-size: var(--font-size-lg);
		font-weight: 700;
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
		width: 1.5rem;
		height: 1.5rem;
		border-radius: 50%;
		background: var(--color-surface-raised);
		border: 1px solid var(--color-border);
		font-size: var(--font-size-sm);
		font-weight: 700;
	}

	.hub-marker--across {
		top: -0.75rem;
		left: 50%;
		translate: -50% 0;
	}

	.hub-marker--self {
		bottom: -0.75rem;
		left: 50%;
		translate: -50% 0;
	}

	.hub-marker--left {
		left: -0.75rem;
		top: 50%;
		translate: 0 -50%;
	}

	.hub-marker--right {
		right: -0.75rem;
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
	// the circle without overlapping one, so they drop and the hub becomes a summary row.
	@include layout.phone-only {
		.center-hub {
			flex-direction: row;
			justify-content: center;
			gap: var(--space-3);
			width: 100%;
			height: auto;
			padding: var(--space-1) var(--space-2);
			border-radius: var(--radius-md);
		}

		.hub-core {
			flex-direction: row;
			gap: var(--space-2);
		}

		.hub-marker {
			display: none;
		}
	}
</style>
