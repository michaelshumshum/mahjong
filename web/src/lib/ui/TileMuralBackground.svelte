<script lang="ts">
	// deliberate exception to the "no canvas" rule (docs/frontend.md §2) -- decorative only,
	// aria-hidden, needs a per-frame blit a DOM grid can't do without animating ~200 elements.
	import { TILE_ASSET, type RenderableTileCode } from '$lib/table/tile-code';
	import { muralBlitY, stepMuralScroll } from './mural-scroll';

	// the tile back joins the pool as its own pseudo-code, same "no suit" treatment as honors.
	type MuralTile = RenderableTileCode | 'back';
	const MURAL_ASSET: Record<MuralTile, string> = { ...TILE_ASSET, back: 'Back' };
	const MURAL_CODES = Object.keys(MURAL_ASSET) as MuralTile[];

	function suitOf(code: MuralTile): 'm' | 'p' | 's' | null {
		if (code === 'back' || code.startsWith('z')) return null;
		return code.slice(-1) as 'm' | 'p' | 's';
	}

	// two rules: no two same-suit tiles share an edge (honors/back exempt), and no two backs
	// share an edge either -- a cluster of backs reads as a "hole" in the mural.
	function pickTile(leftCode: MuralTile | null, topCode: MuralTile | null): MuralTile {
		const leftSuit = leftCode ? suitOf(leftCode) : null;
		const topSuit = topCode ? suitOf(topCode) : null;
		const candidates = MURAL_CODES.filter((code) => {
			if (code === 'back') return leftCode !== 'back' && topCode !== 'back';
			const suit = suitOf(code);
			return suit === null || (suit !== leftSuit && suit !== topSuit);
		});
		return candidates[Math.floor(Math.random() * candidates.length)];
	}

	// buffer is pre-rendered and blitted with a y offset each frame -- drawing ~200 tiles individually
	// dropped frames on a phone-class GPU. Exact 3:4 ratio matches TileFace.svelte; drawTile's math depends on it.
	const TILE_W = 51;
	const TILE_H = 68;
	const GAP = 12;
	const CELL_W = TILE_W + GAP;
	const CELL_H = TILE_H + GAP;
	const SPEED_PX_PER_SEC = 14;

	// vendored SVGs are 300x400, not square -- CSS percentage padding is always width-relative
	// even for top/bottom, so getting this ratio wrong drew the art shrunk into a square.
	const ART_ASPECT = 300 / 400;

	// mounted once in the root layout; `visible` only toggles opacity, never unmounts the canvas,
	// so route changes never restart the scroll or reshuffle the grid.
	let { visible = true }: { visible?: boolean } = $props();

	let canvasEl: HTMLCanvasElement | undefined = $state();

	$effect(() => {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;
		let cancelled = false;

		// --color-tile, not a hardcoded hex, so the mural stays in lockstep with TileFace.svelte.
		const tileColor = getComputedStyle(document.documentElement)
			.getPropertyValue('--color-tile')
			.trim();

		const images = new Map<MuralTile, HTMLImageElement>();
		const decoded = MURAL_CODES.map((code) => {
			const img = new Image();
			img.src = `/tiles/${MURAL_ASSET[code]}.svg`;
			images.set(code, img);
			// img.complete right after setting src is still false -- decode() resolves once the
			// bitmap is actually ready.
			return img.decode().catch(() => {});
		});

		const buffer = document.createElement('canvas');
		const bufferCtxOrNull = buffer.getContext('2d');
		if (!bufferCtxOrNull) return;
		// re-bound to a non-null const: TS doesn't narrow into the nested closures below.
		const bufferCtx: CanvasRenderingContext2D = bufferCtxOrNull;

		const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);

		// persistent across resizes/scroll: cells already assigned a tile keep it, both resize
		// and the scroll loop only ever grow the grid. `topRow` is drawn at the buffer's row 0.
		let grid: MuralTile[][] = [];
		let bufferRows = 0;
		let bufferCssHeight = 0;
		let viewW = 0;
		let viewH = 0;
		let topRow = 0;

		function ensureGrid(cols: number, rows: number): void {
			for (let r = 0; r < grid.length; r++) {
				const row = grid[r];
				for (let c = row.length; c < cols; c++) {
					const left = c > 0 ? row[c - 1] : null;
					const top = r > 0 ? grid[r - 1][c] : null;
					row.push(pickTile(left, top));
				}
			}
			for (let r = grid.length; r < rows; r++) {
				const row: MuralTile[] = [];
				for (let c = 0; c < cols; c++) {
					const left = c > 0 ? row[c - 1] : null;
					const top = r > 0 ? grid[r - 1][c] : null;
					row.push(pickTile(left, top));
				}
				grid.push(row);
			}
		}

		function drawTile(x: number, y: number, code: MuralTile): void {
			const img = images.get(code);
			if (!img?.complete) return;

			if (code === 'back') {
				// mirrors TileFace.svelte's .tile-face--back: no ivory box, full-bleed art.
				bufferCtx.drawImage(img, x, y, TILE_W, TILE_H);
				return;
			}

			bufferCtx.fillStyle = tileColor;
			bufferCtx.beginPath();
			// TileFace.svelte's elliptical border-radius converges to one px value at an exact
			// 3:4 ratio (TILE_W/H), so a single radius is exact here, not an approximation.
			bufferCtx.roundRect(x, y, TILE_W, TILE_H, TILE_H * 0.1);
			bufferCtx.fill();

			// mirrors TileFace.svelte's 7%-of-width padding + object-fit: contain.
			const pad = TILE_W * 0.07;
			const availW = TILE_W - pad * 2;
			const availH = TILE_H - pad * 2;
			let drawW = availW;
			let drawH = drawW / ART_ASPECT;
			if (drawH > availH) {
				drawH = availH;
				drawW = drawH * ART_ASPECT;
			}
			bufferCtx.drawImage(
				img,
				x + pad + (availW - drawW) / 2,
				y + pad + (availH - drawH) / 2,
				drawW,
				drawH
			);
		}

		function renderBuffer(): void {
			if (!canvasEl) return;
			viewW = window.innerWidth;
			viewH = window.innerHeight;

			const cols = Math.ceil(viewW / CELL_W) + 1;
			const visibleRows = Math.ceil(viewH / CELL_H) + 1;
			// one extra row so the sub-row scroll offset never exposes empty space at the bottom.
			bufferRows = visibleRows + 1;
			bufferCssHeight = bufferRows * CELL_H;
			ensureGrid(cols, topRow + bufferRows);

			buffer.width = cols * CELL_W * dpr;
			buffer.height = bufferCssHeight * dpr;
			bufferCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
			bufferCtx.clearRect(0, 0, cols * CELL_W, bufferCssHeight);
			for (let r = 0; r < bufferRows; r++) {
				for (let c = 0; c < cols; c++) {
					drawTile(c * CELL_W, r * CELL_H, grid[topRow + r][c]);
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
				// advances onto a freshly-grown row rather than wrapping via `% CELL_H`, which
				// would read as the mural periodically snapping/reshuffling. See mural-scroll.ts.
				const step = stepMuralScroll(offset, dt, SPEED_PX_PER_SEC, CELL_H);
				offset = step.offset;
				if (step.rowsAdvanced > 0) {
					topRow += step.rowsAdvanced;
					renderBuffer();
				}
			}

			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			ctx.clearRect(0, 0, viewW, viewH);
			ctx.drawImage(buffer, 0, muralBlitY(offset), buffer.width / dpr, bufferCssHeight);

			if (!reduceMotion) raf = requestAnimationFrame(draw);
		}

		// only rebuild on a real size change -- window.innerWidth/innerHeight stay stable across
		// a scrollbar toggling, unlike document.documentElement.clientWidth.
		let resizeTimer = 0;
		function onResize(): void {
			if (window.innerWidth === viewW && window.innerHeight === viewH) return;
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

<canvas bind:this={canvasEl} class="mural" class:mural--hidden={!visible} aria-hidden="true"
></canvas>
<div class="mural-scrim" class:mural--hidden={!visible} aria-hidden="true"></div>

<style lang="scss">
	.mural {
		position: fixed;
		inset: 0;
		z-index: var(--z-table);
		pointer-events: none;
		transition: opacity 220ms ease;
	}

	// sits in front of the canvas and blurs + darkens it so foreground content stays legible.
	.mural-scrim {
		position: fixed;
		inset: 0;
		z-index: var(--z-table);
		pointer-events: none;
		backdrop-filter: blur(3px) brightness(0.55);
		-webkit-backdrop-filter: blur(3px) brightness(0.55);
		background: rgb(0 0 0 / 0.25);
		transition: opacity 220ms ease;
	}

	// routes that don't want the mural still have it mounted underneath, just invisible.
	.mural--hidden {
		opacity: 0;
	}

	@media (prefers-reduced-motion: reduce) {
		.mural,
		.mural-scrim {
			transition: none;
		}
	}
</style>
