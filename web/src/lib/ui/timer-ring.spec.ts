import { describe, it, expect } from 'vitest';
import { computeRingTiming } from './timer-ring';

describe('computeRingTiming', () => {
	it('splits a duration longer than the warn window into deplete + warn segments', () => {
		expect(computeRingTiming(5000)).toEqual({
			depleteDurationMs: 5000,
			warnDelayMs: 3500,
			warnDurationMs: 1500
		});
	});

	it('respects a custom warn window', () => {
		expect(computeRingTiming(3000, 500)).toEqual({
			depleteDurationMs: 3000,
			warnDelayMs: 2500,
			warnDurationMs: 500
		});
	});

	it('treats a duration shorter than the warn window as "about to expire" from the start', () => {
		expect(computeRingTiming(800)).toEqual({
			depleteDurationMs: 800,
			warnDelayMs: 0,
			warnDurationMs: 800
		});
	});

	it('clamps a negative or zero duration to an already-expired ring', () => {
		expect(computeRingTiming(-200)).toEqual({
			depleteDurationMs: 0,
			warnDelayMs: 0,
			warnDurationMs: 0
		});
		expect(computeRingTiming(0)).toEqual({
			depleteDurationMs: 0,
			warnDelayMs: 0,
			warnDurationMs: 0
		});
	});
});
