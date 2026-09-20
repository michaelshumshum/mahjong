// one-shot timeout, not a ticker (docs/03-frontend.md §5 bans a JS ticker for *animation*; this
// is close/expire scheduling, not motion). Returns a disposer so the caller's effect can cancel
// it -- a manually-closed dialog must not also fire `onExpire` later. Shared by every
// timer-driven closable dialog: Toast.svelte uses it directly (no visible ring), DialogTimer.svelte
// pairs it with TimerRing for dialogs that show a countdown.
export function scheduleAutoDismiss(durationMs: number, onExpire: () => void): () => void {
	const handle = setTimeout(onExpire, durationMs);
	return () => clearTimeout(handle);
}
