<script lang="ts">
	import { tick } from 'svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { LIMIT_FAAN } from '$lib/net/protocol.constants';
	import type { TileCode } from '$lib/table/tile-code';
	import TileFace from '$lib/table/TileFace.svelte';
	import { tileName } from '$lib/table/tile-name';
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import StepperField from '$lib/ui/StepperField.svelte';
	import TilePalette from '$lib/ui/TilePalette.svelte';
	import {
		discardComparison,
		discardRows,
		faanMiss,
		safeOutcome,
		safeRows,
		waitsFeedback
	} from './feedback';
	import type { Lesson, SafeReason, WaitOption } from './generated/lessons';
	import { localeList, tileList } from './lesson-text';
	import { SAFE_REASON_LABEL } from './lessons';
	import OptionTable from './OptionTable.svelte';
	import type { Answer, GradeResult, OptionTableRow } from './types';

	// one input per kind; discard kinds pick in the table's hand (the page wires that), then Check.
	// feedback reads the key, never the position; a miss gets hints until "Show answer".
	let {
		lesson,
		answer,
		result,
		attempts,
		explanation,
		seatNames,
		claimedTile = null,
		selectedTile = null,
		revealed = false,
		onAnswer,
		onCheckSelected,
		onReveal,
		onPatternSelect
	}: {
		lesson: Lesson;
		// the last graded answer, `null` before the first
		answer: Answer | null;
		result: GradeResult | null;
		// bumps on every graded answer, so a repeated wrong answer is announced again.
		attempts: number;
		explanation: string;
		// by seat, as the table names them
		seatNames: readonly (string | null)[];
		// a discard win's tile, shown beside the faan input
		claimedTile?: TileCode | null;
		// discard kinds: the tile picked in the hand, not yet graded
		selectedTile?: TileCode | null;
		// the player asked for the answer after a miss
		revealed?: boolean;
		onAnswer: (answer: Answer) => void;
		// discard kinds: grade `selectedTile`
		onCheckSelected?: () => void;
		onReveal?: () => void;
		onPatternSelect?: (pattern: string) => void;
	} = $props();

	let feedbackEl: HTMLDivElement | null = $state(null);

	// the button goes away with the click, so focus moves to what it revealed
	async function reveal(): Promise<void> {
		onReveal?.();
		await tick();
		feedbackEl?.focus();
	}

	interface Line {
		id: string;
		text: string;
		tone: 'good' | 'bad' | 'neutral';
	}

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

	function name(tile: string): string {
		return tileName(tile as TileCode);
	}

	function seatList(seats: readonly number[]): string {
		return localeList(seats.map((seat) => seatNames[seat] ?? ''));
	}

	function reasonList(reasons: readonly SafeReason[]): string {
		return localeList(reasons.map((reason) => SAFE_REASON_LABEL[reason]()));
	}

	function belowMinimumLine(option: WaitOption, tone: Line['tone']): Line {
		return {
			id: 'below-minimum',
			tone,
			text: m.learn_feedbackBelowMinimum({
				tile: name(option.tile),
				discardFaan: option.discard_faan,
				selfDrawFaan: option.self_draw_faan
			})
		};
	}

	// a safe pick that only luck made safe is still wrong, but says so instead of "try again"
	let lucky = $derived(
		lesson.kind === 'safe_discard' &&
			answer?.kind === 'safe_discard' &&
			safeOutcome(lesson.key, answer.tile) === 'lucky'
	);

	// the whole answer: a right one, or a miss once revealed
	let full = $derived(result === 'correct' || (result !== null && revealed));

	let lines = $derived.by((): Line[] => {
		const l = lesson;
		const a = answer;
		if (a === null || result === null) return [];
		if (l.kind === 'best_discard' && a.kind === 'best_discard') {
			const cmp = discardComparison(l.key, a.tile);
			if (!cmp) return [];
			const names = { pick: name(cmp.pick.tile), best: name(cmp.best.tile) };
			return [
				{
					id: 'discard-compare',
					tone: 'bad',
					text:
						cmp.pick.shanten > cmp.best.shanten
							? m.learn_feedbackDiscardFurther(names)
							: m.learn_feedbackDiscardFewer({
									...names,
									pickTiles: cmp.pick.tiles,
									bestTiles: cmp.best.tiles
								})
				}
			];
		}
		if (l.kind === 'winning_tiles' && a.kind === 'winning_tiles') {
			const fb = waitsFeedback(l.key, a.tiles);
			const out: Line[] = [];
			if (result === 'correct') {
				// the teaching points: waits that complete the hand but don't count
				for (const option of fb.belowMinimum) out.push(belowMinimumLine(option, 'neutral'));
				if (fb.dead.length > 0) {
					out.push({
						id: 'dead',
						tone: 'neutral',
						text: m.learn_feedbackDead({ tiles: tileList(fb.dead.map((o) => o.tile)) })
					});
				}
				return out;
			}
			// a hint never names a winning tile; the revealed answer names them all
			if (full) {
				out.push({
					id: 'answer',
					tone: 'good',
					text: m.learn_feedbackWaitsAnswer({ tiles: tileList(l.key.correct) })
				});
			}
			for (const pick of fb.picks) {
				if (pick.verdict === 'below_minimum' && pick.option) {
					out.push(belowMinimumLine(pick.option, 'bad'));
				} else if (pick.verdict === 'dead') {
					out.push({
						id: 'dead',
						tone: 'bad',
						text: m.learn_feedbackDead({ tiles: name(pick.tile) })
					});
				} else if (pick.verdict === 'no_win') {
					out.push({
						id: 'no-win',
						tone: 'bad',
						text: m.learn_feedbackPickNoWin({ tile: name(pick.tile) })
					});
				}
			}
			if (full) {
				// the teaching points the picks didn't already cover
				const pickedTiles = new Set(fb.picks.map((p) => p.tile));
				for (const option of fb.belowMinimum) {
					if (!pickedTiles.has(option.tile)) out.push(belowMinimumLine(option, 'neutral'));
				}
				const dead = fb.dead.filter((o) => !pickedTiles.has(o.tile));
				if (dead.length > 0) {
					out.push({
						id: 'dead',
						tone: 'neutral',
						text: m.learn_feedbackDead({ tiles: tileList(dead.map((o) => o.tile)) })
					});
				}
			} else if (fb.missing > 0) {
				out.push({
					id: 'missing',
					tone: 'neutral',
					text: m.learn_feedbackWaitsMissing({ count: fb.missing })
				});
			}
			return out;
		}
		if (l.kind === 'safe_discard' && a.kind === 'safe_discard') {
			const option = l.key.options.find((o) => o.tile === a.tile);
			switch (safeOutcome(l.key, a.tile)) {
				case 'deducible': {
					const reasons = option?.reasons.length ? option.reasons : [l.key.reason];
					return [
						{
							id: 'why',
							tone: 'good',
							text: m.learn_feedbackSafeWhy({ reason: reasonList(reasons) })
						}
					];
				}
				case 'deals_in':
					return [
						{
							id: 'deals-in',
							tone: 'bad',
							text: m.learn_feedbackDealsIn({
								tile: name(a.tile),
								seats: seatList(option?.deals_in_to ?? [])
							})
						}
					];
				case 'lucky':
					return [];
			}
		}
		if (l.kind === 'count_faan' && a.kind === 'count_faan') {
			const miss = faanMiss(l.key, a.faan);
			if (miss === null) {
				return [
					{ id: 'points', tone: 'neutral', text: m.learn_feedbackPoints({ points: l.key.points }) }
				];
			}
			const out: Line[] = [
				{
					id: `faan-${miss}`,
					tone: 'bad',
					text:
						miss === 'high'
							? m.learn_feedbackFaanHigh({ faan: a.faan })
							: m.learn_feedbackFaanLow({ faan: a.faan })
				}
			];
			if (full) {
				out.push({
					id: 'points',
					tone: 'neutral',
					text: m.learn_feedbackPoints({ points: l.key.points })
				});
			}
			return out;
		}
		return [];
	});

	// the tables give the answer away, so a miss shows them only once revealed
	let table = $derived.by(() => {
		const l = lesson;
		const a = answer;
		if (a === null || !full) return null;
		if (l.kind === 'best_discard' && a.kind === 'best_discard') {
			return {
				testid: 'discard-table',
				caption: m.learn_discardTableCaption(),
				columns: [
					m.learn_discardColumnTile(),
					m.learn_discardColumnShanten(),
					m.learn_discardColumnKinds(),
					m.learn_discardColumnTiles()
				],
				numeric: [2, 3],
				rows: discardRows(l.key, a.tile).map((row): OptionTableRow => ({
					tile: row.tile,
					tone: row.correct ? 'good' : 'neutral',
					answer: row.correct,
					picked: row.picked,
					cells: [
						row.shanten === 0 ? m.learn_shantenReady() : m.learn_shantenAway({ n: row.shanten }),
						String(row.kinds),
						String(row.tiles)
					]
				}))
			};
		}
		if (l.kind === 'safe_discard' && a.kind === 'safe_discard') {
			return {
				testid: 'safe-table',
				caption: m.learn_safeTableCaption(),
				columns: [m.learn_safeColumnTile(), m.learn_safeColumnOutcome()],
				numeric: [],
				rows: safeRows(l.key, a.tile).map((row): OptionTableRow => ({
					tile: row.tile,
					tone:
						row.outcome === 'deducible' ? 'good' : row.outcome === 'deals_in' ? 'bad' : 'neutral',
					answer: row.outcome === 'deducible',
					picked: row.picked,
					cells: [
						row.outcome === 'deducible'
							? m.learn_safeOutcomeDeducible({
									reason: reasonList(row.reasons.length ? row.reasons : [l.key.reason])
								})
							: row.outcome === 'lucky'
								? m.learn_safeOutcomeLucky()
								: m.learn_safeOutcomeDealsIn({ seats: seatList(row.deals_in_to) })
					]
				}))
			};
		}
		return null;
	});

	let breakdown = $derived(
		lesson.kind === 'count_faan' && full
			? lesson.key.breakdown.map((line) => ({ name: line.pattern, faan: line.faan }))
			: null
	);
</script>

<section class="answer-panel" data-testid="answer-panel" data-kind={lesson.kind}>
	{#if lesson.kind === 'best_discard' || lesson.kind === 'safe_discard'}
		<p class="hint">{m.learn_discardHint()}</p>
		<button
			type="button"
			class="check"
			data-testid="answer-check"
			disabled={selectedTile === null}
			onclick={() => onCheckSelected?.()}>{m.learn_checkButton()}</button
		>
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
		{#if claimedTile}
			<p class="claimed" data-testid="claimed-tile">
				<span>{m.learn_claimedTileLabel()}</span>
				<span class="claimed-tile"><TileFace code={claimedTile} /></span>
				<span>{tileName(claimedTile)}</span>
			</p>
		{/if}
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

	<div
		class="feedback"
		role="status"
		tabindex="-1"
		bind:this={feedbackEl}
		data-testid="answer-feedback"
		data-result={result}
		data-lucky={lucky || undefined}
		data-revealed={(result !== 'correct' && full) || undefined}
	>
		{#key attempts}
			{#if result === 'correct'}
				<p class="result result--correct">{m.learn_feedbackCorrect()}</p>
			{:else if result === 'partial'}
				<p class="result">{m.learn_feedbackPartial()}</p>
			{:else if lucky && answer?.kind === 'safe_discard'}
				<p class="result result--lucky">
					{m.learn_feedbackSafeByLuck({ tile: name(answer.tile) })}
				</p>
			{:else if result === 'wrong'}
				<p class="result result--wrong">{m.learn_feedbackWrong()}</p>
			{/if}
			{#if lines.length > 0}
				<ul class="lines">
					{#each lines as line, i (i)}
						<li class="line line--{line.tone}" data-testid="feedback-line" data-line={line.id}>
							{line.text}
						</li>
					{/each}
				</ul>
			{/if}
			{#if full}
				<p class="explain" data-testid="answer-explain">{explanation}</p>
			{/if}
		{/key}
	</div>

	{#if (result === 'wrong' || result === 'partial') && !revealed && onReveal}
		<button type="button" class="reveal" data-testid="answer-reveal" onclick={reveal}
			>{m.learn_showAnswerButton()}</button
		>
	{/if}

	<!-- outside the live region: a whole table read out on every answer is noise -->
	{#if table}
		<OptionTable {...table} />
	{/if}
	{#if breakdown && lesson.kind === 'count_faan'}
		<div class="breakdown" data-testid="faan-breakdown">
			<FaanBreakdown
				winner={0}
				seatNames={{ 0: '', 1: '', 2: '', 3: '' }}
				heading={m.learn_faanBreakdownHeading()}
				winningHand={[]}
				patterns={breakdown}
				totalFaan={lesson.key.correct}
				payments={{}}
				{onPatternSelect}
			/>
		</div>
	{/if}
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

	// a card section here, not the win screen's headline
	.breakdown :global(h2) {
		font-size: var(--font-size-lg);
	}

	.claimed {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
	}

	.claimed-tile {
		display: inline-flex;
		height: 2.5rem;
		border-radius: var(--radius-tile);
		outline: 2px solid var(--color-brass);
		outline-offset: 1px;
	}

	.check {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
		align-self: flex-start;
	}

	.reveal {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-secondary;
		align-self: flex-start;
	}

	// focused only by script, after a reveal; the global ring would frame the whole block
	.feedback:focus {
		outline: none;
	}

	// not :empty: the blocks inside leave whitespace text nodes behind
	.feedback:not(:has(*)) {
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

	.result--lucky {
		color: var(--color-brass);
	}

	.lines {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: var(--space-2) 0 0;
		padding: 0;
		list-style: none;
		line-height: 1.5;
	}

	.line {
		padding-inline-start: var(--space-2);
		border-inline-start: 2px solid var(--color-border);
	}

	.line--good {
		border-color: var(--color-positive);
	}

	.line--bad {
		border-color: var(--color-negative);
	}

	.explain {
		margin: var(--space-2) 0 0;
		line-height: 1.5;
	}
</style>
