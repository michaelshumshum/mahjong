<script lang="ts">
	import TimerRing from '$lib/ui/TimerRing.svelte';
	import { m } from '$lib/paraglide/messages.js';

	const timerDurations = [8000, 3000, 1200];
	let timerDurationMs = $state(timerDurations[0]);
</script>

<h2>{m.timerRingDemo_heading()}</h2>
<p class="hint">{m.timerRingDemo_hint()}</p>
<div class="timer-controls">
	{#each timerDurations as ms (ms)}
		<button type="button" onclick={() => (timerDurationMs = ms)}
			>{m.timerRingDemo_durationButton({ ms })}</button
		>
	{/each}
</div>
{#key timerDurationMs}
	<TimerRing durationMs={timerDurationMs} />
{/key}

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.timer-controls {
		display: flex;
		gap: var(--space-2);
		margin-bottom: var(--space-4);
	}
</style>
