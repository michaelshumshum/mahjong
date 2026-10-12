/** Manual hand order: keeps the player's arrangement for tiles still held, appending newly
 * arrived ones (in `current`'s auto-sorted order) at the right. */
export function reconcileHandOrder(prev: readonly number[], current: readonly number[]): number[] {
	const held = new Set(current);
	const kept = prev.filter((id) => held.has(id));
	const keptSet = new Set(kept);
	return [...kept, ...current.filter((id) => !keptSet.has(id))];
}

/** `order` with `tileId` moved to `toIndex` (clamped); unchanged if the tile isn't in it. */
export function moveTile(order: readonly number[], tileId: number, toIndex: number): number[] {
	const from = order.indexOf(tileId);
	if (from === -1) return order.slice();
	const next = order.filter((id) => id !== tileId);
	next.splice(Math.max(0, Math.min(toIndex, next.length)), 0, tileId);
	return next;
}
