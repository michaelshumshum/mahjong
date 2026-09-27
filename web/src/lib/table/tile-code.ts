// mirrors the tiles.py parsing scheme and the tile set/index layout in docs/01-rules-spec.md §1.

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

// filenames under web/static/tiles/ (samoheen/mahjong-tiles). Winds/dragons keep the old
// repo's romaji names; flowers/seasons use Flor1-4/Seas1-4.
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
	// honors: Ton/Nan/Shaa/Pei = E/S/W/N winds; Chun/Hatsu/Haku = red/green/white dragons.
	// flowers: f1-4 = plum/orchid/chrysanthemum/bamboo; f5-8 = spring/summer/autumn/winter.
	z1: 'Ton',
	z2: 'Nan',
	z3: 'Shaa',
	z4: 'Pei',
	z5: 'Chun',
	z6: 'Hatsu',
	z7: 'Haku',
	f1: 'Flor1',
	f2: 'Flor2',
	f3: 'Flor3',
	f4: 'Flor4',
	f5: 'Seas1',
	f6: 'Seas2',
	f7: 'Seas3',
	f8: 'Seas4'
};

export function hasTileArt(code: TileCode): code is RenderableTileCode {
	return code in TILE_ASSET;
}

const ID_SUITS = ['m', 'p', 's'] as const;

/** Real tile_ids (0..135) -> the `TileCode` they render as, since the wire only gives numeric ids.
 * Flowers never go through here -- the wire already sends those as TileCode strings. */
export function tileIdToCode(tileId: number): TileCode {
	const value = Math.floor(tileId / 4);
	if (value < 27) {
		const suit = ID_SUITS[Math.floor(value / 9)];
		const rank = (value % 9) + 1;
		return `${rank}${suit}` as TileCode;
	}
	return `z${value - 26}` as TileCode;
}
