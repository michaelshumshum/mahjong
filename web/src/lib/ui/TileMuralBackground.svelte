<script lang="ts">
	// deliberate exception to the project's "no canvas" rule (web/AGENTS.md, docs/03-frontend.md
	// §2) -- decorative only, `aria-hidden`, no hit-testing/focus/text-flow to lose, and the
	// scrolling-mural effect this renders needs a per-frame blit a DOM grid can't do without
	// animating ~200 elements' transforms at once. See docs/03-frontend.md §2's canvas exception
	// note for the full rationale.
	import { TILE_ASSET, type RenderableTileCode } from '$lib/table/tile-code';

	// the tile back joins the pool as its own pseudo-code alongside the 34 playable faces --
	// same "special, no suit" treatment as honors (below), and drawn the same way TileFace.svelte
	// draws a concealed tile: full-bleed art, no ivory backing box.
	type MuralTile = RenderableTileCode | 'back';
	const MURAL_ASSET: Record<MuralTile, string> = { ...TILE_ASSET, back: 'Back' };
	const MURAL_CODES = Object.keys(MURAL_ASSET) as MuralTile[];

	function suitOf(code: MuralTile): 'm' | 'p' | 's' | null {
		if (code === 'back' || code.startsWith('z')) return null;
		return code.slice(-1) as 'm' | 'p' | 's';
	}

	// avoids two same-suit tiles sharing an edge; honors and the back have no suit, so they're
	// exempt on both sides of the check -- they can sit next to anything, and anything can sit
	// next to them.
	function pickTile(leftSuit: string | null, topSuit: string | null): MuralTile {
		const candidates = MURAL_CODES.filter((code) => {
			const suit = suitOf(code);
			return suit === null || (suit !== leftSuit && suit !== topSuit);
		});
		return candidates[Math.floor(Math.random() * candidates.length)];
	}

	// css px; buffer is pre-rendered, then just blitted with a y offset each frame -- drawing
	// ~200 tile images individually every frame was the first approach and visibly dropped
	// frames on a phone-class GPU.
	const TILE_W = 64;
	const TILE_H = 84;
	const GAP = 14;
	const CELL_W = TILE_W + GAP;
	const CELL_H = TILE_H + GAP;
	const SPEED_PX_PER_SEC = 14;

	let canvasEl: HTMLCanvasElement | undefined = $state();

	$effect(() => {
		if (!canvasEl) return;
		const ctx = canvasEl.getContext('2d');
		if (!ctx) return;
		let cancelled = false;

		// --color-tile (docs/03-frontend.md §7.1's runtime-custom-property rule) rather than a
		// hardcoded hex, so the mural stays in lockstep with the real tile-face background
		// TileFace.svelte renders on the table itself.
		const tileColor = getComputedStyle(document.documentElement)
			.getPropertyValue('--color-tile')
			.trim();

		const images = new Map<MuralTile, HTMLImageElement>();
		const decoded = MURAL_CODES.map((code) => {
			const img = new Image();
			img.src = `/tiles/${MURAL_ASSET[code]}.svg`;
			images.set(code, img);
			// `img.complete` right after setting `src` is still false -- decode() resolves once
			// the bitmap is actually ready, so the first buffer render has real art to draw
			// instead of racing it and drawing an empty frame.
			return img.decode().catch(() => {});
		});

		const buffer = document.createElement('canvas');
		const bufferCtxOrNull = buffer.getContext('2d');
		if (!bufferCtxOrNull) return;
		// re-bound to a definitely-non-null const: TS doesn't carry the null-check narrowing
		// above into the nested functions below that close over it.
		const bufferCtx: CanvasRenderingContext2D = bufferCtxOrNull;

		const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
		const dpr = Math.min(window.devicePixelRatio || 1, 2);

		// persistent across resizes: cells already assigned a tile keep it, resize only grows
		// the grid to cover the new viewport. Re-randomizing the whole grid on every resize
		// (including spurious ones -- a scrollbar toggling, a webfont swap reflowing the page a
		// couple seconds after load) read as the entire mural "switching," not scrolling.
		let grid: MuralTile[][] = [];
		let bufferRows = 0;
		let bufferCssHeight = 0;
		let viewW = 0;
		let viewH = 0;

		function ensureGrid(cols: number, rows: number): void {
			for (let r = 0; r < grid.length; r++) {
				const row = grid[r];
				for (let c = row.length; c < cols; c++) {
					const left = c > 0 ? suitOf(row[c - 1]) : null;
					const top = r > 0 ? suitOf(grid[r - 1][c]) : null;
					row.push(pickTile(left, top));
				}
			}
			for (let r = grid.length; r < rows; r++) {
				const row: MuralTile[] = [];
				for (let c = 0; c < cols; c++) {
					const left = c > 0 ? suitOf(row[c - 1]) : null;
					const top = r > 0 ? suitOf(grid[r - 1][c]) : null;
					row.push(pickTile(left, top));
				}
				grid.push(row);
			}
		}

		function drawTile(x: number, y: number, code: MuralTile): void {
			const img = images.get(code);
			if (!img?.complete) return;

			if (code === 'back') {
				// mirrors TileFace.svelte's `.tile-face--back`: no ivory box, full-bleed art.
				bufferCtx.drawImage(img, x, y, TILE_W, TILE_H);
				return;
			}

			bufferCtx.fillStyle = tileColor;
			bufferCtx.beginPath();
			bufferCtx.roundRect(x, y, TILE_W, TILE_H, Math.min(TILE_W, TILE_H) * 0.12);
			bufferCtx.fill();

			// mirrors TileFace.svelte's 7% padding + object-fit: contain (art centered in a
			// square within the padded box, since the vendored SVGs are square but the tile
			// box isn't).
			const pad = TILE_W * 0.07;
			const availW = TILE_W - pad * 2;
			const availH = TILE_H - pad * 2;
			const size = Math.min(availW, availH);
			bufferCtx.drawImage(
				img,
				x + pad + (availW - size) / 2,
				y + pad + (availH - size) / 2,
				size,
				size
			);
		}

		function renderBuffer(): void {
			if (!canvasEl) return;
			viewW = window.innerWidth;
			viewH = window.innerHeight;

			const cols = Math.ceil(viewW / CELL_W) + 1;
			const visibleRows = Math.ceil(viewH / CELL_H) + 1;
			bufferRows = visibleRows + 1; // one extra row so the vertical wrap has no seam
			bufferCssHeight = bufferRows * CELL_H;
			ensureGrid(cols, bufferRows);

			buffer.width = cols * CELL_W * dpr;
			buffer.height = bufferCssHeight * dpr;
			bufferCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
			bufferCtx.clearRect(0, 0, cols * CELL_W, bufferCssHeight);
			for (let r = 0; r < bufferRows; r++) {
				for (let c = 0; c < cols; c++) {
					drawTile(c * CELL_W, r * CELL_H, grid[r][c]);
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

		// only rebuild when the viewport actually changed size -- `window.innerWidth/innerHeight`
		// stay stable across a scrollbar toggling (unlike `document.documentElement.clientWidth`),
		// so this also filters out most spurious `resize` events, on top of `ensureGrid` making a
		// real resize non-destructive to the existing layout.
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

<canvas bind:this={canvasEl} class="mural" aria-hidden="true"></canvas>

<style lang="scss">
	.mural {
		position: fixed;
		inset: 0;
		z-index: var(--z-table);
		pointer-events: none;
	}
</style>
