import { describe, expect, it } from 'vitest';
import { muralBlitY, stepMuralScroll } from './mural-scroll';

describe('stepMuralScroll', () => {
	it('advances offset without a row boundary', () => {
		const step = stepMuralScroll(0, 1, 14, 80);
		expect(step.offset).toBeCloseTo(14);
		expect(step.rowsAdvanced).toBe(0);
	});

	it('never lets offset reach or exceed cellH (regression: a plain % wrap read as a snap)', () => {
		let offset = 0;
		for (let i = 0; i < 1000; i++) {
			const step = stepMuralScroll(offset, 1 / 60, 14, 80);
			offset = step.offset;
			expect(offset).toBeGreaterThanOrEqual(0);
			expect(offset).toBeLessThan(80);
		}
	});

	it('advances exactly one row when a single frame crosses one row boundary', () => {
		const step = stepMuralScroll(75, 1, 14, 80);
		expect(step.rowsAdvanced).toBe(1);
		expect(step.offset).toBeCloseTo(9);
	});

	it('advances multiple rows in one step for a large dt (tab backgrounded, then refocused)', () => {
		const step = stepMuralScroll(0, 10, 14, 80);
		expect(step.rowsAdvanced).toBe(1);
		const bigStep = stepMuralScroll(0, 60, 14, 80);
		expect(bigStep.rowsAdvanced).toBe(10);
		expect(bigStep.offset).toBeCloseTo(40);
	});
});

describe('canvas-space row continuity (regression: offset - CELL_H doubled the row-advance shift)', () => {
	const CELL_H = 80;
	const SPEED = 14;

	// mirrors TileMuralBackground's draw(): canvas y for grid row `r` is
	// `(r - topRow) * CELL_H + muralBlitY(offset)`, since renderBuffer places bufferRow
	// `j = r - topRow` at buffer-local y = j * CELL_H.
	function canvasY(row: number, topRow: number, offset: number): number {
		return (row - topRow) * CELL_H + muralBlitY(offset);
	}

	it('never jumps by more than one frame worth of scroll, across many row-boundary crossings', () => {
		let offset = 0;
		let topRow = 0;
		const dt = 1 / 60;
		const trackedRow = 10;
		let prevY: number | null = null;
		let maxJump = 0;

		// ~8s at 14px/s covers several 80px row-boundary crossings (~every 5.7s).
		for (let frame = 0; frame < 60 * 16; frame++) {
			const step = stepMuralScroll(offset, dt, SPEED, CELL_H);
			offset = step.offset;
			topRow += step.rowsAdvanced;

			const y = canvasY(trackedRow, topRow, offset);
			if (prevY !== null) {
				maxJump = Math.max(maxJump, Math.abs(y - prevY));
			}
			prevY = y;
		}

		// a correct frame-to-frame delta is bounded by ~SPEED * dt; the old `offset - CELL_H`
		// formula produced a 2 * CELL_H (160px) jump at every row-boundary crossing instead.
		expect(maxJump).toBeLessThan(SPEED * dt * 2);
	});
});
