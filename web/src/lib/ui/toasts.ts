// pure queue helpers behind Toast.svelte, split out so id assignment is testable without a DOM.
// the reactive `$state<ToastEntry[]>` list lives in the owning .svelte file -- a plain .ts module can't hold runes.

export type ToastSeverity = 'info' | 'warn' | 'error';

export interface ToastEntry {
	id: number;
	message: string;
	durationMs: number;
	severity: ToastSeverity;
}

const DEFAULT_DURATION_MS = 4000;

let nextId = 1;

// monotonic, not array index — an index key breaks keyed `{#each}` identity once a toast in the
// middle of the queue is dismissed and the rest shift down.
export function createToast(
	message: string,
	durationMs = DEFAULT_DURATION_MS,
	severity: ToastSeverity = 'info'
): ToastEntry {
	return { id: nextId++, message, durationMs, severity };
}

export function removeToast(toasts: ToastEntry[], id: number): ToastEntry[] {
	return toasts.filter((toast) => toast.id !== id);
}
