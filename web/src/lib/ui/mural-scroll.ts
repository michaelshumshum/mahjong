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

// y passed to `ctx.drawImage(buffer, 0, y, ...)`. The buffer's own local row layout already
// places bufferRow j (== grid[topRow + j]) at local y = j * cellH (TileMuralBackground's
// `renderBuffer`/`drawTile`), so canvas-space y for that row is `j * cellH + muralBlitY(offset)`.
// Must be `-offset`, not `offset - cellH`: renderBuffer re-anchors the buffer's row 0 to the
// *current* topRow on every advance (no fixed lookahead row baked into the buffer the way the
// old static-buffer scheme had one), so an extra `-cellH` here double-counts the same row-height
// shift topRow's own increment already accounts for -- a `2 * cellH` canvas-space jump every time
// a row advances, which reads as the mural periodically snapping. See
// `mural-scroll.spec.ts`'s continuity regression test.
export function muralBlitY(offset: number): number {
	return -offset;
}
