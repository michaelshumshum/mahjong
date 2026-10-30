<script lang="ts">
	import type { DiscardMode } from './client-prefs';
	import type { CoachTarget } from '$lib/table/view-types';
	import { m } from '$lib/paraglide/messages.js';
	import CoachCard from './CoachCard.svelte';

	let {
		discardMode,
		onStepChange,
		onDone
	}: {
		discardMode: DiscardMode;
		// lets the table outline whatever the current tip points at.
		onStepChange: (target: CoachTarget | null) => void;
		onDone: () => void;
	} = $props();

	let steps = $derived([
		{
			target: 'hand' as const,
			text:
				discardMode === 'two-step' ? m.coachMarks_discardTwoStep() : m.coachMarks_discardOneTap()
		},
		{ target: 'discards' as const, text: m.coachMarks_lastDiscard() },
		{ target: null, text: m.coachMarks_claims() }
	]);

	let index = $state(0);
	let step = $derived(steps[index]);
	let isLast = $derived(index === steps.length - 1);

	$effect(() => {
		onStepChange(step.target);
	});

	function next(): void {
		if (isLast) onDone();
		else index += 1;
	}
</script>

<CoachCard
	label={m.coachMarks_regionLabel()}
	counter={m.coachMarks_stepCounter({ n: index + 1, total: steps.length })}
	testid="coach-mark"
>
	{#key index}
		<p class="coach-text">{step.text}</p>
	{/key}
	{#snippet actions()}
		<button type="button" class="coach-skip" data-testid="coach-skip" onclick={onDone}
			>{m.coachMarks_skipButton()}</button
		>
		<button type="button" class="coach-next" data-testid="coach-next" onclick={next}
			>{isLast ? m.coachMarks_doneButton() : m.coachMarks_nextButton()}</button
		>
	{/snippet}
</CoachCard>
