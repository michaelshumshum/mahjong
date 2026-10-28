<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import TileFace from '$lib/table/TileFace.svelte';
	import { sortTiles, type TileCode } from '$lib/table/tile-code';
	import { tileName } from '$lib/table/tile-name';
	import { SEAT_WINDS, WIND_CHAR } from '$lib/table/wind';
	import { scoreHand, type ScoreHandRequest, type ScoreHandResponse } from '$lib/net/score-hand';
	import SegmentedControl from './SegmentedControl.svelte';
	import SwitchRow from './SwitchRow.svelte';
	import FaanPatternName from './FaanPatternName.svelte';
	import TilePalette from './TilePalette.svelte';

	const HAND_SIZE = 14;
	const COPIES = 4;

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
	let fullyConcealed = $state(true);
	let seatWind = $state('0');
	let prevailingWind = $state('0');

	type Outcome = { kind: 'idle' } | { kind: 'error' } | { kind: 'done'; result: ScoreHandResponse };
	let outcome = $state<Outcome>({ kind: 'idle' });
	// a re-score keeps the last result on screen, dimmed, instead of swapping in a loading line
	let pending = $state(false);

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
			request++;
			pending = false;
			outcome = { kind: 'idle' };
			return;
		}
		const body: ScoreHandRequest = {
			...ruleset,
			tiles: [...tiles],
			flowers: [...flowers],
			self_drawn: winBy === 'self_draw',
			fully_concealed: fullyConcealed,
			seat_wind: Number(seatWind),
			prevailing_wind: Number(prevailingWind)
		};
		const id = ++request;
		pending = true;
		scoreHand(body).then(
			(result) => {
				if (id !== request) return;
				outcome = { kind: 'done', result };
				pending = false;
			},
			() => {
				if (id !== request) return;
				outcome = { kind: 'error' };
				pending = false;
			}
		);
	});
</script>

<div class="checker" data-testid="hand-checker">
	<p class="note intro">{m.guide_checkerIntro()}</p>

	<div class="col col--hand">
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
					<button
						type="button"
						class="tile-btn tile-btn--winning"
						aria-label={m.guide_checkerRemoveTile({ tile: tileName(winningTile) })}
						title={m.guide_checkerWinningTile()}
						onclick={() => removeTile(winningTile, true)}><TileFace code={winningTile} /></button
					>
				{/if}
			</div>
			<div class="hand-meta">
				<span class="count" data-testid="checker-count"
					>{m.guide_checkerCount({ n: tiles.length, total: HAND_SIZE })}</span
				>
				<span class="legend"><span class="swatch"></span>{m.guide_checkerWinningTile()}</span>
				<div class="flowers" aria-label={m.guide_checkerFlowersLabel()} role="group">
					{#each flowers as code (code)}
						<button
							type="button"
							class="tile-btn"
							aria-label={m.guide_checkerRemoveTile({ tile: tileName(code) })}
							onclick={() => (flowers = flowers.filter((f) => f !== code))}
							><TileFace {code} /></button
						>
					{/each}
				</div>
				<button
					type="button"
					class="clear"
					disabled={tiles.length === 0 && flowers.length === 0}
					onclick={clear}>{m.guide_checkerClear()}</button
				>
			</div>
		</div>
		<div
			class="result"
			class:result--pending={pending}
			aria-live="polite"
			aria-busy={pending}
			data-testid="checker-result"
		>
			{#if outcome.kind === 'idle'}
				<p class="note">
					{pending
						? m.guide_checkerScoring()
						: m.guide_checkerPickMore({ count: HAND_SIZE - tiles.length })}
				</p>
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
	</div>

	<div class="col col--pick">
		<div class="palette">
			<TilePalette
				label={m.guide_checkerPaletteLabel()}
				tileLabel={(code) => m.guide_checkerAddTile({ tile: tileName(code) })}
				onPick={add}
				canPick={canAdd}
				testidPrefix="checker-add-"
			/>
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
			<div class="concealed" data-testid="checker-fully-concealed">
				<SwitchRow
					label={m.guide_checkerFullyConcealed()}
					checked={fullyConcealed}
					onChange={(next) => (fullyConcealed = next)}
				/>
			</div>
		</div>
	</div>
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
	}

	// one column: the wrappers dissolve and `order` puts the hand above the palette
	.col {
		display: contents;
	}

	.intro,
	.hand-row,
	.palette,
	.options,
	.result {
		flex-shrink: 0;
	}

	.hand-row {
		order: 1;
	}

	.palette {
		order: 2;
	}

	.options {
		order: 3;
	}

	.result {
		order: 4;
	}

	.note {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.hand-row {
		container-type: inline-size;
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		padding: var(--space-2);
		border-radius: var(--radius-sm);
		background: var(--color-felt);
		box-shadow: inset 0 2px 6px rgb(0 0 0 / 0.35);
	}

	// one row at any width: tiles shrink to fit all 14 (3:4 faces, 2px gaps, the winning tile's
	// extra gap), so picking never wraps the hand onto a second line
	.hand {
		--gaps: calc(13 * 2px + var(--space-2));
		--tile-h: min(2.75rem, calc((100cqi - var(--gaps)) / 14 * 4 / 3));
		display: flex;
		align-items: flex-end;
		gap: 2px;
		height: calc(var(--tile-h) + 6px);

		.tile-btn {
			height: var(--tile-h);
		}
	}

	.hand-meta {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		height: 2rem;
		font-size: var(--font-size-sm);
	}

	.count {
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}

	.legend {
		display: inline-flex;
		align-items: center;
		gap: var(--space-1);
		white-space: nowrap;
		color: var(--color-text-muted);
	}

	.swatch {
		width: 0.75rem;
		height: 0.75rem;
		border-radius: 2px;
		box-shadow: inset 0 0 0 2px var(--color-brass);
	}

	.flowers {
		display: flex;
		gap: 2px;
		flex: 1;
		min-width: 0;
		overflow: hidden;

		.tile-btn {
			height: 1.6rem;
		}
	}

	.clear {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
		min-height: 28px;
		flex-shrink: 0;
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
		margin-inline-start: var(--space-2);
		border-radius: var(--radius-sm);
		box-shadow: 0 0 0 2px var(--color-brass);
	}

	.col--pick {
		--palette-tile-h: 2.25rem;
	}

	.options {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		gap: var(--space-3);
	}

	.concealed {
		min-width: 12rem;
	}

	// fixed: a result never grows or shrinks the view; a long breakdown scrolls inside it
	.result {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		height: 9.5rem;
		overflow-y: auto;
		transition: opacity var(--dur-1) ease;
	}

	.result--pending {
		opacity: 0.55;
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

	// two columns: pick on the left, the hand and its score on the right, so the result is in
	// view while picking
	@container guide-view (min-width: 46rem) {
		.checker {
			display: grid;
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
			grid-template-areas:
				'intro intro'
				'pick hand';
			align-content: start;
			gap: var(--space-4) var(--space-6);
		}

		.intro {
			grid-area: intro;
		}

		.col {
			display: flex;
			flex-direction: column;
			gap: var(--space-3);
		}

		.col--pick {
			grid-area: pick;
			--palette-tile-h: 2.75rem;
		}

		.col--hand {
			grid-area: hand;
		}

		.result {
			height: 16rem;
		}
	}
</style>
