// pure timing math behind TimerRing.svelte, split out so it's testable without a DOM/CSS
// animation clock (docs/protocol.md §4: last ~1.5s reads as "about to expire", not exact).

export interface RingTiming {
	// depleteDurationMs: full ring length. warnDelayMs: offset (from start) when "about to expire"
	// kicks in. warnDurationMs: length of that "about to expire" transition itself.
	depleteDurationMs: number;
	warnDelayMs: number;
	warnDurationMs: number;
}

export function computeRingTiming(durationMs: number, warnWindowMs = 1500): RingTiming {
	const depleteDurationMs = Math.max(durationMs, 0);
	const warnDurationMs = Math.min(warnWindowMs, depleteDurationMs);
	const warnDelayMs = depleteDurationMs - warnDurationMs;
	return { depleteDurationMs, warnDelayMs, warnDurationMs };
}
