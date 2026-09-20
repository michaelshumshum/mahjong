// pure queue helpers behind Toast.svelte, split out so id assignment is testable without a DOM.
// Auto-close scheduling lives in ./auto-close (shared with every other timer-driven closable
// dialog, not toast-specific). The reactive `$state<ToastEntry[]>` list itself lives in whichever
// .svelte file owns the queue (e.g. the demo page), not here: a plain .ts module can't hold runes.

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
