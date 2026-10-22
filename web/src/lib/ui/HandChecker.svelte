<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import TileFace from '$lib/table/TileFace.svelte';
	import { sortTiles, type TileCode } from '$lib/table/tile-code';
	import { tileName } from '$lib/table/tile-name';
	import { SEAT_WINDS, WIND_CHAR } from '$lib/table/wind';
	import { scoreHand, type ScoreHandRequest, type ScoreHandResponse } from '$lib/net/score-hand';
	import SegmentedControl from './SegmentedControl.svelte';
	import FaanPatternName from './FaanPatternName.svelte';

	const HAND_SIZE = 14;
	const COPIES = 4;
	const SUITS = ['m', 'p', 's'] as const;
	const RANKS = [1, 2, 3, 4, 5, 6, 7, 8, 9] as const;
	const PALETTE: TileCode[][] = [
		...SUITS.map((suit) => RANKS.map((rank) => `${rank}${suit}` as TileCode)),
		['z1', 'z2', 'z3', 'z4', 'z5', 'z6', 'z7'],
		['f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8']
	];

	let {
		ruleset,
		onPatternSelect
	}: {
		// what POST /score resolves the rules from
		ruleset: Pick<ScoreHandRequest, 'ruleset' | 'rules'>;
		onPatternSelect?: (pattern: string) => void;
	} = $props();

	// in pick order: the last one is the winning tile
	let tiles = $state<TileCode[]>([]);
	let flowers = $state<TileCode[]>([]);
	let winBy = $state<'discard' | 'self_draw'>('discard');
	let seatWind = $state('0');
	let prevailingWind = $state('0');

	type Outcome =
		| { kind: 'idle' }
		| { kind: 'loading' }
		| { kind: 'error' }
		| { kind: 'done'; result: ScoreHandResponse };
	let outcome = $state<Outcome>({ kind: 'idle' });

	let complete = $derived(tiles.length === HAND_SIZE);
	let shown = $derived(complete ? sortTiles(tiles.slice(0, -1)) : sortTiles(tiles));
	let winningTile = $derived(complete ? tiles[HAND_SIZE - 1] : null);

	const isFlower = (code: TileCode): boolean => code.startsWith('f');

	function canAdd(code: TileCode): boolean {
		if (isFlower(code)) return !flowers.includes(code);
		return !complete && tiles.filter((t) => t === code).length < COPIES;
	}

	function add(code: TileCode): void {
		if (!canAdd(code)) return;
		if (isFlower(code)) flowers = [...flowers, code];
		else tiles = [...tiles, code];
	}

	function removeTile(code: TileCode, fromWinning = false): void {
		const index = fromWinning ? tiles.length - 1 : tiles.indexOf(code);
		tiles = tiles.filter((_, i) => i !== index);
	}

	function clear(): void {
		tiles = [];
		flowers = [];
	}

	const windOptions = SEAT_WINDS.map((wind, i) => ({ value: String(i), label: WIND_CHAR[wind] }));

	let request = 0;
	$effect(() => {
		if (!complete) {
			outcome = { kind: 'idle' };
			return;
		}
		const body: ScoreHandRequest = {
			...ruleset,
			tiles: [...tiles],
			flowers: [...flowers],
			self_drawn: winBy === 'self_draw',
			seat_wind: Number(seatWind),
			prevailing_wind: Number(prevailingWind)
		};
		const id = ++request;
		outcome = { kind: 'loading' };
		scoreHand(body).then(
			(result) => {
				if (id === request) outcome = { kind: 'done', result };
			},
			() => {
				if (id === request) outcome = { kind: 'error' };
			}
		);
	});
</script>

<div class="checker" data-testid="hand-checker">
	<p class="note">{m.guide_checkerIntro()}</p>

	<div class="hand-row">
		<div class="hand" aria-label={m.guide_checkerHandLabel()} role="group">
			{#each shown as code, i (`${i}:${code}`)}
				<button
					type="button"
					class="tile-btn"
					aria-label={m.guide_checkerRemoveTile({ tile: tileName(code) })}
					onclick={() => removeTile(code)}><TileFace {code} /></button
				>
			{/each}
			{#if winningTile}
				<span class="winning">
					<button
						type="button"
						class="tile-btn tile-btn--winning"
						aria-label={m.guide_checkerRemoveTile({ tile: tileName(winningTile) })}
						onclick={() => removeTile(winningTile, true)}><TileFace code={winningTile} /></button
					>
					<span class="winning-label">{m.guide_checkerWinningTile()}</span>
				</span>
			{/if}
			{#each flowers as code (code)}
				<button
					type="button"
					class="tile-btn tile-btn--flower"
					aria-label={m.guide_checkerRemoveTile({ tile: tileName(code) })}
					onclick={() => (flowers = flowers.filter((f) => f !== code))}><TileFace {code} /></button
				>
			{/each}
		</div>
		<div class="hand-meta">
			<span class="count" data-testid="checker-count"
				>{m.guide_checkerCount({ n: tiles.length, total: HAND_SIZE })}</span
			>
			<button
				type="button"
				class="clear"
				disabled={tiles.length === 0 && flowers.length === 0}
				onclick={clear}>{m.guide_checkerClear()}</button
			>
		</div>
	</div>

	<div class="palette" role="group" aria-label={m.guide_checkerPaletteLabel()}>
		{#each PALETTE as row, r (r)}
			<div class="palette-row">
				{#each row as code (code)}
					<button
						type="button"
						class="tile-btn"
						disabled={!canAdd(code)}
						aria-label={m.guide_checkerAddTile({ tile: tileName(code) })}
						data-testid={`checker-add-${code}`}
						onclick={() => add(code)}><TileFace {code} /></button
					>
				{/each}
			</div>
		{/each}
	</div>

	<div class="options">
		<SegmentedControl
			legend={m.guide_checkerWinBy()}
			name="checker-win-by"
			options={[
				{ value: 'discard', label: m.guide_checkerDiscard() },
				{ value: 'self_draw', label: m.guide_checkerSelfDraw() }
			]}
			value={winBy}
			onChange={(next) => (winBy = next)}
		/>
		<SegmentedControl
			legend={m.guide_checkerSeatWind()}
			name="checker-seat-wind"
			options={windOptions}
			value={seatWind}
			onChange={(next) => (seatWind = next)}
		/>
		<SegmentedControl
			legend={m.guide_checkerPrevailingWind()}
			name="checker-prevailing-wind"
			options={windOptions}
			value={prevailingWind}
			onChange={(next) => (prevailingWind = next)}
		/>
	</div>

	<div class="result" aria-live="polite" data-testid="checker-result">
		{#if outcome.kind === 'idle'}
			<p class="note">{m.guide_checkerPickMore({ count: HAND_SIZE - tiles.length })}</p>
		{:else if outcome.kind === 'loading'}
			<p class="note">{m.guide_checkerScoring()}</p>
		{:else if outcome.kind === 'error'}
			<p class="note">{m.guide_checkerError()}</p>
		{:else if !outcome.result.winning}
			<p class="verdict verdict--miss">{m.guide_checkerNotWinning()}</p>
		{:else}
			<ul class="breakdown">
				{#each Object.entries(outcome.result.breakdown) as [name, faan] (name)}
					<li>
						<FaanPatternName {name} onSelect={onPatternSelect} />
						<span class="faan">{m.guide_tabFaan({ count: faan })}</span>
					</li>
				{/each}
			</ul>
			<p class="verdict">
				{m.guide_checkerTotal({
					faan: outcome.result.total_faan ?? 0,
					points: outcome.result.points ?? 0
				})}
			</p>
			{#if outcome.result.clears_min_faan === false}
				<p class="verdict verdict--miss">
					{m.guide_checkerBelowMin({ min: outcome.result.min_faan })}
				</p>
			{/if}
		{/if}
	</div>
	<p class="note">{m.guide_checkerLimits()}</p>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.checker {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);

		> * {
			flex-shrink: 0;
		}
	}

	.note {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.hand-row {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-felt);
		box-shadow: inset 0 2px 6px rgb(0 0 0 / 0.35);
	}

	.hand {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: 2px;
		min-height: 2.75rem;
	}

	.winning {
		display: inline-flex;
		flex-direction: column;
		align-items: center;
		margin-inline: var(--space-2);
	}

	.winning-label {
		font-size: var(--font-size-xs);
		color: var(--color-brass);
	}

	.hand-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.count {
		font-variant-numeric: tabular-nums;
	}

	.clear {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
		min-height: 32px;
	}

	.tile-btn {
		display: inline-block;
		height: 2.75rem;
		padding: 0;
		border: 0;
		background: none;
		cursor: pointer;

		&:disabled {
			cursor: default;
			opacity: 0.3;
		}
	}

	.tile-btn--winning {
		box-shadow: 0 0 0 2px var(--color-brass);
		border-radius: var(--radius-sm);
	}

	.tile-btn--flower {
		margin-inline-start: var(--space-2);
	}

	.palette {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.palette-row {
		display: flex;
		flex-wrap: wrap;
		gap: 2px;

		.tile-btn {
			height: 2.25rem;
		}
	}

	.options {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.result {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		min-height: 3rem;
	}

	.breakdown {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;

		li {
			display: flex;
			justify-content: space-between;
			gap: var(--space-3);
			border-bottom: 1px dashed color-mix(in srgb, var(--color-border) 70%, transparent);
		}
	}

	.faan {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.verdict {
		margin: 0;
		font-weight: 600;
	}

	.verdict--miss {
		color: var(--color-negative);
	}
</style>
