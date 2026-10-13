import type { TileCode } from './tile-code';

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
