import { m } from '$lib/paraglide/messages.js';
import type { TileCode } from './tile-code';

export const TILE_NAME: Record<TileCode, () => string> = {
	'1m': m.tileName_1m,
	'2m': m.tileName_2m,
	'3m': m.tileName_3m,
	'4m': m.tileName_4m,
	'5m': m.tileName_5m,
	'6m': m.tileName_6m,
	'7m': m.tileName_7m,
	'8m': m.tileName_8m,
	'9m': m.tileName_9m,
	'1p': m.tileName_1p,
	'2p': m.tileName_2p,
	'3p': m.tileName_3p,
	'4p': m.tileName_4p,
	'5p': m.tileName_5p,
	'6p': m.tileName_6p,
	'7p': m.tileName_7p,
	'8p': m.tileName_8p,
	'9p': m.tileName_9p,
	'1s': m.tileName_1s,
	'2s': m.tileName_2s,
	'3s': m.tileName_3s,
	'4s': m.tileName_4s,
	'5s': m.tileName_5s,
	'6s': m.tileName_6s,
	'7s': m.tileName_7s,
	'8s': m.tileName_8s,
	'9s': m.tileName_9s,
	z1: m.tileName_z1,
	z2: m.tileName_z2,
	z3: m.tileName_z3,
	z4: m.tileName_z4,
	z5: m.tileName_z5,
	z6: m.tileName_z6,
	z7: m.tileName_z7,
	f1: m.tileName_f1,
	f2: m.tileName_f2,
	f3: m.tileName_f3,
	f4: m.tileName_f4,
	f5: m.tileName_f5,
	f6: m.tileName_f6,
	f7: m.tileName_f7,
	f8: m.tileName_f8
};

/** Localized spoken name ("Red Dragon"/紅中) for alt text and aria-labels -- never the raw code. */
export function tileName(code: TileCode): string {
	return TILE_NAME[code]();
}

/** Distinct tiles in first-seen order: a kong/pung option's tiles are one face repeated. */
export function distinctTiles(codes: readonly TileCode[]): TileCode[] {
	return [...new Set(codes)];
}

/** "{label}: {tile names}" for a button whose visible tiles are aria-hidden previews. */
export function tileOptionAriaLabel(label: string, codes: readonly TileCode[]): string {
	const tiles = distinctTiles(codes).map(tileName).join(m.tileOption_listSeparator());
	return m.tileOption_ariaLabel({ label, tiles });
}
