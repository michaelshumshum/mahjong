<script lang="ts">
	// deliberate exception to the "no canvas" rule (docs/frontend.md §2) -- decorative only,
	// aria-hidden; one canvas instead of ~200 DOM tiles. scroll is a CSS transform, not a JS ticker.
	import { TILE_ASSET, type RenderableTileCode } from '$lib/table/tile-code';
	import { isMotionReduced } from './motion';

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

	// exact 3:4 ratio matches TileFace.svelte; drawTile's math depends on it.
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
	// set once the tiles are drawn; reduced motion leaves it false (static grid).
	let animated = $state(false);

	$effect(() => {
		if (!canvasEl) return;
		const ctxOrNull = canvasEl.getContext('2d');
		if (!ctxOrNull) return;
		// re-bound to a non-null const: TS doesn't narrow into the nested closures below.
		const ctx: CanvasRenderingContext2D = ctxOrNull;
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

		const reduceMotion = isMotionReduced();
		const dpr = Math.min(window.devicePixelRatio || 1, 2);

		// persistent across resizes/scroll: cells already assigned a tile keep it, both resize
		// and each row advance only ever grow the grid. `topRow` is drawn at the canvas's row 0.
		let grid: MuralTile[][] = [];
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
				ctx.drawImage(img, x, y, TILE_W, TILE_H);
				return;
			}

			ctx.fillStyle = tileColor;
			ctx.beginPath();
			// TileFace.svelte's elliptical border-radius converges to one px value at an exact
			// 3:4 ratio (TILE_W/H), so a single radius is exact here, not an approximation.
			ctx.roundRect(x, y, TILE_W, TILE_H, TILE_H * 0.1);
			ctx.fill();

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
			ctx.drawImage(
				img,
				x + pad + (availW - drawW) / 2,
				y + pad + (availH - drawH) / 2,
				drawW,
				drawH
			);
		}

		// one row taller than the viewport: the CSS animation slides it up by exactly one row,
		// then each iteration redraws one row further down and the transform snaps back to 0.
		function render(): void {
			if (!canvasEl) return;
			viewW = window.innerWidth;
			viewH = window.innerHeight;
			const cols = Math.ceil(viewW / CELL_W) + 1;
			const rows = Math.ceil(viewH / CELL_H) + 2;
			ensureGrid(cols, topRow + rows);

			canvasEl.width = cols * CELL_W * dpr;
			canvasEl.height = rows * CELL_H * dpr;
			canvasEl.style.width = `${cols * CELL_W}px`;
			canvasEl.style.height = `${rows * CELL_H}px`;
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			ctx.clearRect(0, 0, cols * CELL_W, rows * CELL_H);
			for (let r = 0; r < rows; r++) {
				for (let c = 0; c < cols; c++) {
					drawTile(c * CELL_W, r * CELL_H, grid[topRow + r][c]);
				}
			}
		}

		// animationiteration fires before that frame paints, so the redraw and the transform
		// reset land together -- no visible jump.
		function onIteration(): void {
			topRow++;
			render();
		}
		canvasEl.addEventListener('animationiteration', onIteration);

		// only rebuild on a real size change -- window.innerWidth/innerHeight stay stable across
		// a scrollbar toggling, unlike document.documentElement.clientWidth.
		let resizeTimer = 0;
		function onResize(): void {
			if (window.innerWidth === viewW && window.innerHeight === viewH) return;
			window.clearTimeout(resizeTimer);
			resizeTimer = window.setTimeout(render, 150);
		}
		window.addEventListener('resize', onResize);

		Promise.all(decoded).then(() => {
			if (cancelled) return;
			render();
			if (!reduceMotion) animated = true;
		});

		return () => {
			cancelled = true;
			canvasEl?.removeEventListener('animationiteration', onIteration);
			window.clearTimeout(resizeTimer);
			window.removeEventListener('resize', onResize);
		};
	});
</script>

<canvas
	bind:this={canvasEl}
	class="mural"
	class:mural--animated={animated}
	class:mural--hidden={!visible}
	style:--mural-row="{CELL_H}px"
	style:--mural-row-dur="{(CELL_H / SPEED_PX_PER_SEC) * 1000}ms"
	aria-hidden="true"
></canvas>
<div class="mural-scrim" class:mural--hidden={!visible} aria-hidden="true"></div>

<style lang="scss">
	@use '$lib/styles/a11y';
	// filter on the canvas itself, not a backdrop-filter scrim: a full-viewport backdrop-filter
	// re-sampled every frame made the cursor flicker on macOS Chrome.
	.mural {
		position: fixed;
		top: 0;
		left: 0;
		z-index: var(--z-table);
		pointer-events: none;
		filter: blur(3px) brightness(0.5);
		transition: opacity 220ms ease;
	}

	// transform-only, so the scroll runs on the compositor with no per-frame paint.
	.mural--animated {
		animation: mural-scroll var(--mural-row-dur) linear infinite;
	}

	@keyframes mural-scroll {
		to {
			transform: translateY(calc(-1 * var(--mural-row)));
		}
	}

	// darkens the middle so foreground content stays legible.
	.mural-scrim {
		position: fixed;
		inset: 0;
		z-index: var(--z-table);
		pointer-events: none;
		// darker in the middle, where lobby/pre-game copy sits over the mural.
		background: radial-gradient(
			ellipse 70% 60% at 50% 50%,
			rgb(0 0 0 / 0.6),
			rgb(0 0 0 / 0.3) 75%,
			rgb(0 0 0 / 0.2)
		);
		transition: opacity 220ms ease;
	}

	// routes that don't want the mural still have it mounted underneath, just invisible.
	.mural--hidden {
		opacity: 0;
		animation-play-state: paused;
	}

	.mural,
	.mural-scrim {
		@include a11y.motion-reduced {
			transition: none;
		}
	}
</style>
