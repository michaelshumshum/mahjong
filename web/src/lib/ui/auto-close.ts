// one-shot timeout, not a ticker -- returns a disposer so a manually-closed dialog doesn't
// also fire `onExpire` later. Shared by every timer-driven closable dialog.
export function scheduleAutoDismiss(durationMs: number, onExpire: () => void): () => void {
	const handle = setTimeout(onExpire, durationMs);
	return () => clearTimeout(handle);
}
