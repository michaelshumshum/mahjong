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

	// same one-shot-timeout contract as Toast.svelte -- fires `onClose` once, at `durationMs`,
	// anchored fresh whenever the prop changes (a new deadline in the parent naturally
	// reschedules rather than drifting off a stale timer).
	$effect(() => scheduleAutoDismiss(durationMs, onClose));
</script>

<TimerRing {durationMs} {size} {warnWindowMs} />
