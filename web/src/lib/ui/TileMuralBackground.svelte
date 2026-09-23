<script lang="ts">
	// deliberate exception to the project's "no canvas" rule (web/AGENTS.md, docs/03-frontend.md
	// §2) -- decorative only, `aria-hidden`, no hit-testing/focus/text-flow to lose, and the
	// scrolling-mural effect this renders needs a per-frame blit a DOM grid can't do without
	// animating ~200 elements' transforms at once. See docs/03-frontend.md §2's canvas exception
	// note for the full rationale.
	import { TILE_ASSET, type RenderableTileCode } from '$lib/table/tile-code';

	const CODES = Object.keys(TILE_ASSET) as RenderableTileCode[];

	// css px; buffer is pre-rendered once per resize, then just blitted with a y offset each
	// frame -- drawing ~200 tile images individually every frame was the first approach and
	// visibly dropped frames on a phone-class GPU.
	const TILE_W = 64;
	const TILE_H = 84;
	const GAP = 14;
	const CELL_W = TILE_W + GAP;
	const CELL_H = TILE_H + GAP;
	const SPEED_PX_PER_SEC = 14;
	const OPACITY = 0.12;

	let canvasEl: HTMLCanvasElement | undefined = $state();

	$effect(() => {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;
		let cancelled = false;

		const images = new Map<RenderableTileCode, HTMLImageElement>();
		const decoded = CODES.map((code) => {
			const img = new Image();
			img.src = `/tiles/${TILE_ASSET[code]}.svg`;
			images.set(code, img);
			// `img.complete` right after setting `src` is still false -- decode() resolves once
			// the bitmap is actually ready, so the first buffer render has real art to draw
			// instead of racing it and drawing an empty frame that then never gets rebuilt
			// (the buffer is otherwise only re-rendered on resize).
			return img.decode().catch(() => {});
		});

		const buffer = document.createElement('canvas');
		const bufferCtx = buffer.getContext('2d');
		if (!bufferCtx) return;

		const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);

		let grid: RenderableTileCode[][] = [];
		let bufferRows = 0;
		let bufferCssHeight = 0;
		let viewW = 0;
		let viewH = 0;

		function renderBuffer(): void {
			if (!canvasEl || !bufferCtx) return;
			viewW = window.innerWidth;
			viewH = window.innerHeight;

			const cols = Math.ceil(viewW / CELL_W) + 1;
			const visibleRows = Math.ceil(viewH / CELL_H) + 1;
			bufferRows = visibleRows + 1; // one extra row so the vertical wrap has no seam
			bufferCssHeight = bufferRows * CELL_H;

			grid = Array.from({ length: bufferRows }, () =>
				Array.from({ length: cols }, () => CODES[Math.floor(Math.random() * CODES.length)])
			);

			buffer.width = cols * CELL_W * dpr;
			buffer.height = bufferCssHeight * dpr;
			bufferCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
			bufferCtx.clearRect(0, 0, cols * CELL_W, bufferCssHeight);
			bufferCtx.globalAlpha = OPACITY;
			for (let r = 0; r < bufferRows; r++) {
				for (let c = 0; c < cols; c++) {
					const img = images.get(grid[r][c]);
					if (!img?.complete) continue;
					bufferCtx.drawImage(img, c * CELL_W, r * CELL_H, TILE_W, TILE_H);
				}
			}

			canvasEl.width = viewW * dpr;
			canvasEl.height = viewH * dpr;
			canvasEl.style.width = `${viewW}px`;
			canvasEl.style.height = `${viewH}px`;
		}

		let offset = 0;
		let last = performance.now();
		let raf = 0;

		function draw(now: number): void {
			if (!canvasEl || !ctx) return;
			const dt = (now - last) / 1000;
			last = now;
			if (!reduceMotion) {
				offset = (offset + SPEED_PX_PER_SEC * dt) % CELL_H;
			}

			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			ctx.clearRect(0, 0, viewW, viewH);
			ctx.drawImage(buffer, 0, offset - CELL_H, buffer.width / dpr, bufferCssHeight);

			if (!reduceMotion) raf = requestAnimationFrame(draw);
		}

		// a fresh random grid on resize reads as "redrawn for the new size," not a glitch --
		// same crossfade-on-resync justification docs/03-frontend.md §6 gives for state_sync.
		let resizeTimer = 0;
		function onResize(): void {
			window.clearTimeout(resizeTimer);
			resizeTimer = window.setTimeout(renderBuffer, 150);
		}
		window.addEventListener('resize', onResize);

		Promise.all(decoded).then(() => {
			if (cancelled) return;
			renderBuffer();
			last = performance.now();
			draw(last);
		});

		return () => {
			cancelled = true;
			cancelAnimationFrame(raf);
			window.clearTimeout(resizeTimer);
			window.removeEventListener('resize', onResize);
		};
	});
</script>

<canvas bind:this={canvasEl} class="mural" aria-hidden="true"></canvas>

<style lang="scss">
	.mural {
		position: fixed;
		inset: 0;
		z-index: var(--z-table);
		pointer-events: none;
	}
</style>
