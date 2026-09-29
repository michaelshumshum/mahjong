import { describe, expect, it } from 'vitest';
import { hasTileArt, TILE_ASSET, tileIdToCode, type TileCode } from './tile-code';

const ALL_TILE_CODES: TileCode[] = [
	...Array.from({ length: 9 }, (_, i) => `${i + 1}m` as TileCode),
	...Array.from({ length: 9 }, (_, i) => `${i + 1}p` as TileCode),
	...Array.from({ length: 9 }, (_, i) => `${i + 1}s` as TileCode),
	...Array.from({ length: 7 }, (_, i) => `z${i + 1}` as TileCode),
	...Array.from({ length: 8 }, (_, i) => `f${i + 1}` as TileCode)
];

const HONOR_START = 27 * 4; // 108

describe('TILE_ASSET', () => {
	it('maps every known tile code to a non-empty asset name', () => {
		for (const code of ALL_TILE_CODES) {
			expect(TILE_ASSET[code]).toBeTruthy();
		}
	});

	it('uses the expected asset names for representative tiles', () => {
		expect(TILE_ASSET['1m']).toBe('Man1');
		expect(TILE_ASSET['9p']).toBe('Pin9');
		expect(TILE_ASSET['5s']).toBe('Sou5');
		expect(TILE_ASSET.z1).toBe('Ton');
		expect(TILE_ASSET.z5).toBe('Chun');
		expect(TILE_ASSET.f1).toBe('Flor1');
		expect(TILE_ASSET.f5).toBe('Seas1');
	});
});

describe('hasTileArt', () => {
	it('returns true for every renderable tile code', () => {
		for (const code of ALL_TILE_CODES) {
			expect(hasTileArt(code)).toBe(true);
		}
	});

	it('returns false for an unknown tile code', () => {
		expect(hasTileArt('xx' as TileCode)).toBe(false);
	});
});

describe('tileIdToCode', () => {
	it('round-trips every numeric tile id through a defined code', () => {
		for (let id = 0; id < 136; id++) {
			const code = tileIdToCode(id);
			expect(ALL_TILE_CODES).toContain(code);
		}
	});

	it('maps the first id of each suit to rank 1', () => {
		expect(tileIdToCode(0)).toBe('1m');
		expect(tileIdToCode(36)).toBe('1p');
		expect(tileIdToCode(72)).toBe('1s');
	});

	it('maps the last id of each suit to rank 9', () => {
		expect(tileIdToCode(35)).toBe('9m');
		expect(tileIdToCode(71)).toBe('9p');
		expect(tileIdToCode(107)).toBe('9s');
	});

	it('maps the four copies of the same tile to the same code', () => {
		expect(tileIdToCode(0)).toBe('1m');
		expect(tileIdToCode(1)).toBe('1m');
		expect(tileIdToCode(2)).toBe('1m');
		expect(tileIdToCode(3)).toBe('1m');
	});

	it('maps honor tile ids to z1..z7', () => {
		expect(tileIdToCode(HONOR_START)).toBe('z1');
		expect(tileIdToCode(HONOR_START + 3)).toBe('z1');
		expect(tileIdToCode(HONOR_START + 4)).toBe('z2');
		expect(tileIdToCode(HONOR_START + 27)).toBe('z7');
		expect(tileIdToCode(135)).toBe('z7');
	});
});
