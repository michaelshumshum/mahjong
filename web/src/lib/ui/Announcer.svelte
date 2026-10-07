<script lang="ts">
	import { followTopmostDialog } from './ModalDialog.svelte';

	// one polite live region per page (frontend.md §9). announce() queues; a burst (a resync, a
	// call landing with its discard) settles into one update instead of interrupting itself.
	const SETTLE_MS = 300;
	const MAX_LINES = 4;

	let text = $state('');
	let pending: string[] = [];
	let timer: ReturnType<typeof setTimeout> | null = null;
	let alternate = false;

	function flush(): void {
		timer = null;
		const lines = pending.slice(-MAX_LINES);
		pending = [];
		if (lines.length === 0) return;
		// a trailing zero-width space toggles so an identical repeat still changes the region.
		alternate = !alternate;
		text = lines.join('. ') + (alternate ? '​' : '');
	}

	export function announce(lines: string | string[]): void {
		const next = typeof lines === 'string' ? [lines] : lines;
		if (next.length === 0) return;
		pending.push(...next);
		if (timer !== null) clearTimeout(timer);
		timer = setTimeout(flush, SETTLE_MS);
	}

	$effect(() => () => {
		if (timer !== null) clearTimeout(timer);
	});
</script>

<!-- the region moves into an open modal (followTopmostDialog), or it would be inert there. -->
<div class="announcer-home">
	<div
		class="sr-only"
		role="status"
		aria-live="polite"
		aria-atomic="true"
		data-testid="announcer"
		{@attach followTopmostDialog}
	>
		{text}
	</div>
</div>

<style>
	.announcer-home {
		display: contents;
	}
</style>
