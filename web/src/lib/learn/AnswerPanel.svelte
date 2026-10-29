<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { LIMIT_FAAN } from '$lib/net/protocol.constants';
	import type { TileCode } from '$lib/table/tile-code';
	import { tileName } from '$lib/table/tile-name';
	import type { DiscardMode } from '$lib/ui/client-prefs';
	import StepperField from '$lib/ui/StepperField.svelte';
	import TilePalette from '$lib/ui/TilePalette.svelte';
	import type { Lesson } from './generated/lessons';
	import type { Answer, GradeResult } from './types';

	// one input per kind; discard kinds answer by tapping the table's hand (the page wires that).
	// per-kind feedback beyond the result line hangs off `result` here.
	let {
		lesson,
		discardMode,
		result,
		attempts,
		explanation,
		onAnswer
	}: {
		lesson: Lesson;
		discardMode: DiscardMode;
		result: GradeResult | null;
		// bumps on every graded answer, so a repeated wrong answer is announced again.
		attempts: number;
		explanation: string;
		onAnswer: (answer: Answer) => void;
	} = $props();

	let picked = $state<ReadonlySet<TileCode>>(new Set());
	let faan = $state<number | null>(null);

	function toggle(code: TileCode): void {
		const next = new Set(picked);
		if (!next.delete(code)) next.add(code);
		picked = next;
	}

	function checkWaits(): void {
		onAnswer({ kind: 'winning_tiles', tiles: [...picked] });
	}

	function checkFaan(): void {
		if (faan !== null) onAnswer({ kind: 'count_faan', faan });
	}
</script>

<section class="answer-panel" data-testid="answer-panel" data-kind={lesson.kind}>
	{#if lesson.kind === 'best_discard' || lesson.kind === 'safe_discard'}
		<p class="hint">
			{discardMode === 'one-tap' ? m.learn_discardHintOneTap() : m.learn_discardHintTwoStep()}
		</p>
	{:else if lesson.kind === 'winning_tiles'}
		<TilePalette
			label={m.learn_winningTilesLabel()}
			tileLabel={tileName}
			onPick={toggle}
			selected={picked}
			flowers={false}
			testidPrefix="answer-tile-"
		/>
		<button
			type="button"
			class="check"
			data-testid="answer-check"
			disabled={picked.size === 0}
			onclick={checkWaits}>{m.learn_checkButton()}</button
		>
	{:else}
		<form
			class="faan-form"
			onsubmit={(e) => {
				e.preventDefault();
				checkFaan();
			}}
		>
			<StepperField
				label={m.learn_faanLabel()}
				value={faan}
				min={0}
				max={LIMIT_FAAN}
				testid="answer-faan"
				onChange={(next) => (faan = next)}
			/>
			<button type="submit" class="check" data-testid="answer-check" disabled={faan === null}
				>{m.learn_checkButton()}</button
			>
		</form>
	{/if}

	<div class="feedback" role="status" data-testid="answer-feedback" data-result={result}>
		{#key attempts}
			{#if result === 'correct'}
				<p class="result result--correct">{m.learn_feedbackCorrect()}</p>
				<p class="explain" data-testid="answer-explain">{explanation}</p>
			{:else if result === 'partial'}
				<p class="result">{m.learn_feedbackPartial()}</p>
			{:else if result === 'wrong'}
				<p class="result result--wrong">{m.learn_feedbackWrong()}</p>
			{/if}
		{/key}
	</div>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.answer-panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hint {
		margin: 0;
		color: var(--color-text-muted);
	}

	.faan-form {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.check {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
		align-self: flex-start;
	}

	.feedback:empty {
		display: none;
	}

	.result {
		margin: 0;
		font-weight: 700;
	}

	.result--correct {
		color: var(--color-positive);
	}

	.result--wrong {
		color: var(--color-negative);
	}

	.explain {
		margin: var(--space-2) 0 0;
		line-height: 1.5;
	}
</style>
