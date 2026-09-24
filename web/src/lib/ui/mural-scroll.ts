// pure scroll-window math for TileMuralBackground's canvas draw loop -- extracted so the
// row-advance logic is unit-testable without a canvas or a real requestAnimationFrame loop.
export function stepMuralScroll(
	offset: number,
	dt: number,
	speedPxPerSec: number,
	cellH: number
): { offset: number; rowsAdvanced: number } {
	let next = offset + speedPxPerSec * dt;
	let rowsAdvanced = 0;
	while (next >= cellH) {
		next -= cellH;
		rowsAdvanced++;
	}
	return { offset: next, rowsAdvanced };
}

// must be `-offset`, not `offset - cellH`: renderBuffer re-anchors the buffer's row 0 to the
// current topRow on every advance, so an extra `-cellH` here double-counts that shift, causing
// a 2*cellH jump every row advance. See mural-scroll.spec.ts's continuity regression test.
export function muralBlitY(offset: number): number {
	return -offset;
}
