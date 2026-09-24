<script lang="ts">
	import TimerRing from './TimerRing.svelte';
	import { scheduleAutoDismiss } from './auto-close';

	let {
		durationMs,
		onClose,
		size = 56,
		warnWindowMs = 1500
	}: {
		durationMs: number;
		onClose: () => void;
		size?: number;
		warnWindowMs?: number;
	} = $props();

	// same one-shot-timeout contract as Toast.svelte -- re-anchors whenever durationMs changes.
	$effect(() => scheduleAutoDismiss(durationMs, onClose));
</script>

<TimerRing {durationMs} {size} {warnWindowMs} />
