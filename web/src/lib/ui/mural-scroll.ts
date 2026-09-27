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

// must be `-offset`, not `offset - cellH`: renderBuffer re-anchors row 0 to topRow every advance,
// so an extra `-cellH` here double-counts the shift (see mural-scroll.spec.ts's regression test).
export function muralBlitY(offset: number): number {
	return -offset;
}
