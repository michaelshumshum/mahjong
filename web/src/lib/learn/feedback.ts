// what the feedback shows, read off the answer key only (ADR 0025): like grade.ts, nothing here
// knows a mahjong rule.

import { sortTiles, type TileCode } from '$lib/table/tile-code';
import type {
	BestDiscardKey,
	CountFaanKey,
	DiscardOption,
	SafeDiscardKey,
	SafeOption,
	WaitOption,
	WinningTilesKey
} from './generated/lessons';
import type { SafeOutcome, WaitVerdict } from './types';

export interface DiscardRow extends DiscardOption {
	correct: boolean;
	picked: boolean;
}

/** Every option best first: fewest steps from ready, then most tiles accepted. */
export function discardRows(key: BestDiscardKey, pick: string | null): DiscardRow[] {
	return key.options
		.map((option) => ({
			...option,
			correct: key.correct.includes(option.tile),
			picked: option.tile === pick
		}))
		.sort((a, b) => a.shanten - b.shanten || b.tiles - a.tiles);
}

/** A wrong pick beside the best option, for the one-line comparison; `null` for a right one. */
export function discardComparison(
	key: BestDiscardKey,
	pick: string
): { pick: DiscardOption; best: DiscardOption } | null {
	if (key.correct.includes(pick)) return null;
	const picked = key.options.find((option) => option.tile === pick);
	const best = key.options.find((option) => option.tile === key.correct[0]);
	return picked && best ? { pick: picked, best } : null;
}

export interface WaitPick {
	tile: string;
	verdict: WaitVerdict;
	option: WaitOption | null;
}

export interface WaitsFeedback {
	/** the player's picks in tile order */
	picks: WaitPick[];
	/** correct waits not picked */
	missing: number;
	belowMinimum: WaitOption[];
	dead: WaitOption[];
}

export function waitVerdict(key: WinningTilesKey, tile: string): WaitVerdict {
	if (key.correct.includes(tile)) return 'wins';
	if (key.below_minimum.includes(tile)) return 'below_minimum';
	if (key.dead.includes(tile)) return 'dead';
	return 'no_win';
}

export function waitsFeedback(key: WinningTilesKey, picked: readonly string[]): WaitsFeedback {
	const option = (tile: string) => key.options.find((o) => o.tile === tile) ?? null;
	const options = (tiles: readonly string[]) =>
		tiles.map(option).filter((o): o is WaitOption => o !== null);
	return {
		picks: sortTiles(picked as TileCode[]).map((tile) => ({
			tile,
			verdict: waitVerdict(key, tile),
			option: option(tile)
		})),
		missing: key.correct.filter((tile) => !picked.includes(tile)).length,
		belowMinimum: options(key.below_minimum),
		dead: options(key.dead)
	};
}

export interface SafeRow extends SafeOption {
	outcome: SafeOutcome;
	picked: boolean;
}

export function safeOutcome(key: SafeDiscardKey, tile: string): SafeOutcome {
	if (key.correct.includes(tile)) return 'deducible';
	return key.safe.includes(tile) ? 'lucky' : 'deals_in';
}

/** Every tile in the hand, in the key's order. */
export function safeRows(key: SafeDiscardKey, pick: string | null): SafeRow[] {
	return key.options.map((option) => ({
		...option,
		outcome: safeOutcome(key, option.tile),
		picked: option.tile === pick
	}));
}

/** Which way a wrong faan count missed; `null` when it is right. */
export function faanMiss(key: CountFaanKey, faan: number): 'high' | 'low' | null {
	if (faan === key.correct) return null;
	return faan > key.correct ? 'high' : 'low';
}
