// pure queue helpers behind Toast.svelte, split out so id assignment and dismiss-scheduling are
// testable without a DOM or real elapsed time — same pure-logic-extraction pattern as
// timer-ring.ts. The reactive `$state<ToastEntry[]>` list itself lives in whichever .svelte file
// owns the queue (e.g. the demo page), not here: a plain .ts module can't hold runes.

export interface ToastEntry {
	id: number;
	message: string;
	durationMs: number;
}

const DEFAULT_DURATION_MS = 4000;

let nextId = 1;

// monotonic, not array index — an index key breaks keyed `{#each}` identity once a toast in the
// middle of the queue is dismissed and the rest shift down.
export function createToast(message: string, durationMs = DEFAULT_DURATION_MS): ToastEntry {
	return { id: nextId++, message, durationMs };
}

export function removeToast(toasts: ToastEntry[], id: number): ToastEntry[] {
	return toasts.filter((toast) => toast.id !== id);
}

// one-shot timeout, not a ticker (docs/03-frontend.md §5 bans a JS ticker for *animation*; this
// is dismiss scheduling, not motion). Returns a disposer so the caller's effect can cancel it —
// a manually-dismissed toast must not also fire `onExpire` later.
export function scheduleAutoDismiss(durationMs: number, onExpire: () => void): () => void {
	const handle = setTimeout(onExpire, durationMs);
	return () => clearTimeout(handle);
}
