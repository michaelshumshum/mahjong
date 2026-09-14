// mirrors the tiles.py parsing scheme (docs/05-roadmap.md §1, docs/02-protocol.md's
// `"tile": "5s"` wire field) and the tile set/index layout in docs/01-rules-spec.md §1.

type ManTile = '1m' | '2m' | '3m' | '4m' | '5m' | '6m' | '7m' | '8m' | '9m';
type PinTile = '1p' | '2p' | '3p' | '4p' | '5p' | '6p' | '7p' | '8p' | '9p';
type SouTile = '1s' | '2s' | '3s' | '4s' | '5s' | '6s' | '7s' | '8s' | '9s';

// z1-z4 winds (E S W N), z5-z7 dragons (中 發 白) — docs/01-rules-spec.md §1's index layout.
type HonorTile = 'z1' | 'z2' | 'z3' | 'z4' | 'z5' | 'z6' | 'z7';

// f1-f4 flowers, f5-f8 seasons — docs/01-rules-spec.md §1. No vendored art for these yet,
// see the TILE_ASSET comment below and NOTICE.
type FlowerTile = 'f1' | 'f2' | 'f3' | 'f4' | 'f5' | 'f6' | 'f7' | 'f8';

export type TileCode = ManTile | PinTile | SouTile | HonorTile | FlowerTile;

/** codes with vendored face art (the 34 playable tiles; no flowers/seasons — see NOTICE) */
export type RenderableTileCode = ManTile | PinTile | SouTile | HonorTile;

// filenames (extension-less) under web/static/tiles/, from FluffyStuff/riichi-mahjong-tiles
// "Regular" style. Winds/dragons keep the source repo's romaji names.
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
	z7: 'Haku' // 白, white dragon
};

export function hasTileArt(code: TileCode): code is RenderableTileCode {
	return code in TILE_ASSET;
}
