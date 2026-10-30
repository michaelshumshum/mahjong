<script lang="ts">
	import type { Snippet } from 'svelte';
	import { m } from '$lib/paraglide/messages.js';
	import CoachCard from '$lib/ui/CoachCard.svelte';

	let {
		step,
		total,
		tip,
		move,
		wrongMoves,
		busy,
		canBack,
		canNext,
		onBack,
		onNext,
		children,
		end
	}: {
		/** 1-based among the steps that wait on the player. */
		step: number;
		total: number;
		tip: string;
		/** the tip asks for a move on the table rather than "Next". */
		move: boolean;
		wrongMoves: number;
		/** the other seats are playing: no move or "Next" yet. */
		busy: boolean;
		canBack: boolean;
		canNext: boolean;
		onBack: () => void;
		onNext: () => void;
		children?: Snippet;
		/** the last step's buttons, in place of "Next". */
		end?: Snippet;
	} = $props();

	let tipEl: HTMLElement | undefined = $state();
	let nextEl: HTMLButtonElement | undefined = $state();

	// a move or "Next" drops focus: land it on Next, else the tip. deferred, so a closing claim
	// dialog has handed focus back first.
	$effect(() => {
		void step;
		void wrongMoves;
		const handle = setTimeout(() => {
			const active = document.activeElement;
			const lost = !active || active === document.body || !active.isConnected || active === tipEl;
			if (lost) (nextEl ?? tipEl)?.focus();
		});
		return () => clearTimeout(handle);
	});
</script>

<CoachCard
	label={m.learn_tutorialCoachLabel()}
	counter={m.learn_tutorialStepCounter({ n: step, total })}
	testid="tutorial-coach"
>
	<p class="coach-text" tabindex="-1" bind:this={tipEl} data-testid="tutorial-tip">{tip}</p>
	{#if busy}
		<p class="coach-note" data-testid="tutorial-watching">{m.learn_tutorialWatching()}</p>
	{:else if move && wrongMoves > 0}
		{#key wrongMoves}
			<p class="coach-note coach-note--wrong" data-testid="tutorial-hint">
				{m.learn_tutorialWrongMove()}
			</p>
		{/key}
	{/if}
	{@render children?.()}
	{#snippet actions()}
		{#if canBack}
			<button type="button" class="coach-skip" data-testid="tutorial-back" onclick={onBack}
				>{m.learn_tutorialBack()}</button
			>
		{/if}
		{#if end}
			{@render end()}
		{:else if canNext}
			<button
				type="button"
				class="coach-next"
				data-testid="tutorial-next"
				bind:this={nextEl}
				onclick={onNext}>{m.learn_tutorialNext()}</button
			>
		{/if}
	{/snippet}
</CoachCard>

<style lang="scss">
	.coach-text:focus {
		outline: none;
	}

	.coach-note {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.coach-note--wrong {
		color: var(--color-negative);
		font-weight: 600;
	}
</style>
