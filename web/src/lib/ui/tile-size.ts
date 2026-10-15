import type { TileSize } from './client-prefs';

/** Mirrors the tile size setting onto `html[data-tile-size]`, which `app.scss` turns into
 * `--tile-scale`. */
export function applyTileSize(size: TileSize, root: HTMLElement = document.documentElement): void {
	root.dataset.tileSize = size;
}
