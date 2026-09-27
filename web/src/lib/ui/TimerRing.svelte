<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { computeRingTiming } from './timer-ring';

	let {
		durationMs,
		warnWindowMs = 1500,
		size = 56
	}: { durationMs: number; warnWindowMs?: number; size?: number } = $props();

	// anchored once per instance, not re-measured on a JS ticker -- a new deadline gets a new
	// instance (keyed by window_id), restarting the CSS animations from render time.
	let timing = $derived(computeRingTiming(durationMs, warnWindowMs));

	const RADIUS = 45;
	const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
	const secondsLabel = $derived(Math.max(Math.ceil(durationMs / 1000), 0));

	// a single inline `style` string rather than several `style:--x` directives — custom
	// properties mixed with unit suffixes ("{n}ms") are simplest to get right this way.
	const ringStyle = $derived(
		`--ring-size: ${size}px; --deplete-duration: ${timing.depleteDurationMs}ms; ` +
			`--warn-delay: ${timing.warnDelayMs}ms; --warn-duration: ${timing.warnDurationMs}ms; ` +
			`--circumference: ${CIRCUMFERENCE}px`
	);
</script>

<div
	class="timer-ring"
	role="timer"
	aria-label={m.timerRing_remainingLabel({ seconds: secondsLabel })}
	style={ringStyle}
>
	<svg viewBox="0 0 100 100">
		<circle class="track" cx="50" cy="50" r={RADIUS} />
		<circle class="progress" cx="50" cy="50" r={RADIUS} stroke-dasharray={CIRCUMFERENCE} />
	</svg>
</div>

<style lang="scss">
	.timer-ring {
		width: var(--ring-size);
		height: var(--ring-size);
	}

	svg {
		width: 100%;
		height: 100%;
		transform: rotate(-90deg); // 12 o'clock start
	}

	circle {
		fill: none;
		stroke-width: 8;
	}

	.track {
		stroke: var(--color-border);
	}

	.progress {
		stroke: var(--color-accent);
		stroke-linecap: round;
		animation:
			deplete var(--deplete-duration) linear forwards,
			warn-pulse var(--warn-duration) var(--warn-delay) linear forwards;
	}

	@media (prefers-reduced-motion: reduce) {
		.progress {
			animation: none;
			stroke-dashoffset: 0;
		}
	}

	@keyframes deplete {
		from {
			stroke-dashoffset: 0;
		}
		to {
			stroke-dashoffset: var(--circumference);
		}
	}

	// last warnWindowMs: shift from accent to error and pulse -- no numeric readout, just a state change.
	@keyframes warn-pulse {
		0% {
			stroke: var(--color-accent);
			opacity: 1;
		}
		50% {
			stroke: var(--color-status-error);
			opacity: 0.6;
		}
		100% {
			stroke: var(--color-status-error);
			opacity: 1;
		}
	}
</style>
