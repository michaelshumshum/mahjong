import type { MeldKind } from '$lib/game/types';
import { sortTiles, tileSortKey, type TileCode } from './tile-code';

/** The code a meld's `index`th tile shows, `null` for a face-down back. A concealed kong (暗槓)
 * is laid HK-style: both end tiles face-down, the middle two face-up. */
export function meldTileFace(
	kind: string,
	code: TileCode,
	index: number,
	length: number
): TileCode | null {
	return kind === 'concealed_kong' && (index === 0 || index === length - 1) ? null : code;
}

// Cantonese call glyph stamped on a new meld (SealStamp); kongs of every kind read 槓.
export const MELD_SEAL_GLYPH: Record<MeldKind, string> = {
	chow: '上',
	pung: '碰',
	exposed_kong: '槓',
	concealed_kong: '槓',
	added_kong: '槓'
};

/** Each meld's tiles sorted, then the melds by their first tile, so several claimed sets read
 * left-to-right in the same suit order as the concealed tiles beside them. */
export function sortMelds<T extends { tiles: TileCode[] }>(melds: T[]): T[] {
	return melds
		.map((meld) => ({ ...meld, tiles: sortTiles(meld.tiles) }))
		.sort((a, b) => tileSortKey(a.tiles[0]) - tileSortKey(b.tiles[0]));
}
