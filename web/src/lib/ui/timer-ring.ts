// pure timing math behind TimerRing.svelte, split out so it's testable without a DOM/CSS
// animation clock (docs/02-protocol.md §4: last ~1.5s reads as "about to expire", not exact).

export interface RingTiming {
	depleteDurationMs: number; // full ring animation length
	warnDelayMs: number; // when the "about to expire" state kicks in, relative to start
	warnDurationMs: number; // how long the "about to expire" transition itself takes
}

export function computeRingTiming(durationMs: number, warnWindowMs = 1500): RingTiming {
	const depleteDurationMs = Math.max(durationMs, 0);
	const warnDurationMs = Math.min(warnWindowMs, depleteDurationMs);
	const warnDelayMs = depleteDurationMs - warnDurationMs;
	return { depleteDurationMs, warnDelayMs, warnDurationMs };
}
