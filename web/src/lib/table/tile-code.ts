// mirrors the tiles.py parsing scheme (docs/05-roadmap.md §1, docs/02-protocol.md's
// `"tile": "5s"` wire field) and the tile set/index layout in docs/01-rules-spec.md §1.

type ManTile = '1m' | '2m' | '3m' | '4m' | '5m' | '6m' | '7m' | '8m' | '9m';
type PinTile = '1p' | '2p' | '3p' | '4p' | '5p' | '6p' | '7p' | '8p' | '9p';
type SouTile = '1s' | '2s' | '3s' | '4s' | '5s' | '6s' | '7s' | '8s' | '9s';

// z1-z4 winds (E S W N), z5-z7 dragons (中 發 白) — docs/01-rules-spec.md §1's index layout.
type HonorTile = 'z1' | 'z2' | 'z3' | 'z4' | 'z5' | 'z6' | 'z7';

// f1-f4 flowers, f5-f8 seasons — docs/01-rules-spec.md §1.
type FlowerTile = 'f1' | 'f2' | 'f3' | 'f4' | 'f5' | 'f6' | 'f7' | 'f8';

export type TileCode = ManTile | PinTile | SouTile | HonorTile | FlowerTile;

/** codes with vendored face art (all 42 tile faces; see NOTICE) */
export type RenderableTileCode = ManTile | PinTile | SouTile | HonorTile | FlowerTile;

// filenames (extension-less) under web/static/tiles/, from samoheen/mahjong-tiles
// Hong Kong set. Winds/dragons keep the old repo's romaji names; flowers/seasons use
// Flor1-4 / Seas1-4 to match the terse naming scheme.
export const TILE_ASSET: Record<RenderableTileCode, string> = {
	'1m': 'Man1',
	'2m': 'Man2',
	'3m': 'Man3',
	'4m': 'Man4',
	'5m': 'Man5',
	'6m': 'Man6',
	'7m': 'Man7',
	'8m': 'Man8',
	'9m': 'Man9',
	'1p': 'Pin1',
	'2p': 'Pin2',
	'3p': 'Pin3',
	'4p': 'Pin4',
	'5p': 'Pin5',
	'6p': 'Pin6',
	'7p': 'Pin7',
	'8p': 'Pin8',
	'9p': 'Pin9',
	'1s': 'Sou1',
	'2s': 'Sou2',
	'3s': 'Sou3',
	'4s': 'Sou4',
	'5s': 'Sou5',
	'6s': 'Sou6',
	'7s': 'Sou7',
	'8s': 'Sou8',
	'9s': 'Sou9',
	z1: 'Ton', // East
	z2: 'Nan', // South
	z3: 'Shaa', // West
	z4: 'Pei', // North
	z5: 'Chun', // 中, red dragon
	z6: 'Hatsu', // 發, green dragon
	z7: 'Haku', // 白, white dragon
	f1: 'Flor1', // plum
	f2: 'Flor2', // orchid
	f3: 'Flor3', // chrysanthemum
	f4: 'Flor4', // bamboo
	f5: 'Seas1', // spring
	f6: 'Seas2', // summer
	f7: 'Seas3', // autumn
	f8: 'Seas4' // winter
};

export function hasTileArt(code: TileCode): code is RenderableTileCode {
	return code in TILE_ASSET;
}

const ID_SUITS = ['m', 'p', 's'] as const;

/** Real tile_ids (0..135) -> the `TileCode` they render as. Mirrors `tiles.py`'s
 * `tile_id_type` (`tile_id // 4` -> the canonical 0..33 `TileType`, docs/01-rules-spec.md §1)
 * composed with `tile_code()`'s string rendering -- the wire protocol only ever gives this
 * seat's own tiles (and any public meld) as numeric ids (docs/02-protocol.md §3), never a
 * code, so the live table view needs this to draw them through the same `TileFace` the mock
 * scenarios already feed a `TileCode` directly. Flowers never go through here -- the wire
 * sends `flowers` as `TileCode` strings (`'f1'..'f8'`) already. */
export function tileIdToCode(tileId: number): TileCode {
	const value = Math.floor(tileId / 4);
	if (value < 27) {
		const suit = ID_SUITS[Math.floor(value / 9)];
		const rank = (value % 9) + 1;
		return `${rank}${suit}` as TileCode;
	}
	return `z${value - 26}` as TileCode;
}
