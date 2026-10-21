<script lang="ts">
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';

	interface Point {
		ts: number;
		value: number | null;
	}

	let {
		label,
		points,
		format,
		testid
	}: {
		label: string;
		points: Point[];
		format: (value: number) => string;
		testid?: string;
	} = $props();

	const WIDTH = 600;
	const HEIGHT = 96;
	// headroom so the peak never touches the top edge
	const Y_HEADROOM = 1.15;

	let values = $derived(points.flatMap((p) => (p.value === null ? [] : [p.value])));
	let drawable = $derived(values.length >= 2);
	let t0 = $derived(points[0]?.ts ?? 0);
	let t1 = $derived(points.at(-1)?.ts ?? 0);
	let yMax = $derived(Math.max(1, ...values) * Y_HEADROOM);

	function x(ts: number): number {
		return t1 === t0 ? 0 : ((ts - t0) / (t1 - t0)) * WIDTH;
	}

	function y(value: number): number {
		return HEIGHT - (value / yMax) * HEIGHT;
	}

	// a null value (no bot move in that window) breaks the line instead of dropping to zero
	let segments = $derived.by(() => {
		const runs: Point[][] = [];
		let run: Point[] = [];
		for (const p of points) {
			if (p.value === null) {
				if (run.length) runs.push(run);
				run = [];
			} else {
				run.push(p);
			}
		}
		if (run.length) runs.push(run);
		return runs;
	});

	let paths = $derived(
		segments.map((run) => {
			const line = run
				.map((p, i) => `${i ? 'L' : 'M'}${x(p.ts).toFixed(1)},${y(p.value!).toFixed(1)}`)
				.join('');
			const area = `${line}L${x(run.at(-1)!.ts).toFixed(1)},${HEIGHT}L${x(run[0].ts).toFixed(1)},${HEIGHT}Z`;
			return { line, area };
		})
	);

	let summary = $derived(
		drawable
			? m.statusPage_chartSummary({
					label,
					latest: format(values.at(-1)!),
					peak: format(Math.max(...values))
				})
			: label
	);

	let hoverIndex = $state<number | null>(null);
	let hovered = $derived(hoverIndex === null ? null : points[hoverIndex]);

	function onPointerMove(event: PointerEvent): void {
		const rect = (event.currentTarget as SVGElement).getBoundingClientRect();
		const ts = t0 + ((event.clientX - rect.left) / rect.width) * (t1 - t0);
		let best = 0;
		for (let i = 1; i < points.length; i++) {
			if (Math.abs(points[i].ts - ts) < Math.abs(points[best].ts - ts)) best = i;
		}
		hoverIndex = best;
	}

	function timeLabel(ts: number): string {
		return new Date(ts).toLocaleTimeString(getLocale(), { hour: 'numeric', minute: '2-digit' });
	}
</script>

<figure class="sparkline" data-testid={testid}>
	<figcaption>
		<span class="label">{label}</span>
		<span class="range">{m.statusPage_chartRange()}</span>
	</figcaption>
	{#if drawable}
		<div class="plot">
			<svg
				viewBox="0 0 {WIDTH} {HEIGHT}"
				preserveAspectRatio="none"
				role="img"
				aria-label={summary}
				onpointermove={onPointerMove}
				onpointerleave={() => (hoverIndex = null)}
			>
				<line class="baseline" x1="0" x2={WIDTH} y1={HEIGHT} y2={HEIGHT} />
				{#each paths as { line, area } (line)}
					<path class="area" d={area} />
					<path class="line" d={line} />
				{/each}
				{#if hovered}
					<line class="crosshair" x1={x(hovered.ts)} x2={x(hovered.ts)} y1="0" y2={HEIGHT} />
				{/if}
			</svg>
			{#if hovered}
				<div
					class="tooltip"
					style:left="{(x(hovered.ts) / WIDTH) * 100}%"
					data-testid="sparkline-tooltip"
				>
					<span class="tooltip-value"
						>{hovered.value === null ? m.statusPage_notAvailable() : format(hovered.value)}</span
					>
					<span class="tooltip-time">{timeLabel(hovered.ts)}</span>
				</div>
			{/if}
		</div>
	{:else}
		<p class="empty">{m.statusPage_chartEmpty()}</p>
	{/if}
</figure>

<style lang="scss">
	.sparkline {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		margin: 0;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);
	}

	figcaption {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	.label {
		font-weight: 600;
	}

	.range,
	.empty {
		color: var(--color-text-muted);
	}

	.empty {
		margin: 0;
		font-size: var(--font-size-sm);
	}

	.plot {
		position: relative;
	}

	svg {
		display: block;
		width: 100%;
		height: 6rem;
		overflow: visible;
		touch-action: pan-y;
	}

	.baseline,
	.crosshair {
		stroke: var(--color-border);
		stroke-width: 1px;
		vector-effect: non-scaling-stroke;
	}

	.crosshair {
		stroke: var(--color-text-muted);
	}

	.line {
		fill: none;
		stroke: var(--color-brass);
		stroke-width: 2px;
		stroke-linejoin: round;
		vector-effect: non-scaling-stroke;
	}

	.area {
		fill: color-mix(in srgb, var(--color-brass) 18%, transparent);
	}

	.tooltip {
		position: absolute;
		bottom: calc(100% + var(--space-1));
		display: flex;
		flex-direction: column;
		padding: var(--space-1) var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		font-size: var(--font-size-xs);
		white-space: nowrap;
		transform: translateX(-50%);
		pointer-events: none;
	}

	.tooltip-value {
		font-weight: 600;
	}

	.tooltip-time {
		color: var(--color-text-muted);
	}
</style>
