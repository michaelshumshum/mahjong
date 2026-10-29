import { describe, expect, it } from 'vitest';
import isolatedHonour from './generated/basics-isolated-honour.json';
import noChance from './generated/basics-no-chance.json';
import simpleHand from './generated/basics-simple-hand.json';
import twoSidedWait from './generated/basics-two-sided-wait.json';
import type { Lesson } from './generated/lessons';
import { grade } from './grade';

const bestDiscard = isolatedHonour as unknown as Lesson;
const safeDiscard = noChance as unknown as Lesson;
const countFaan = simpleHand as unknown as Lesson;
const winningTiles = twoSidedWait as unknown as Lesson;

describe('grade', () => {
	it('best_discard: a key tile is correct, any other wrong', () => {
		expect(grade(bestDiscard, { kind: 'best_discard', tile: 'z5' }).result).toBe('correct');
		expect(grade(bestDiscard, { kind: 'best_discard', tile: '1m' }).result).toBe('wrong');
	});

	it('safe_discard: a tile in the accepted set is correct, any other wrong', () => {
		expect(grade(safeDiscard, { kind: 'safe_discard', tile: '1m' }).result).toBe('correct');
		expect(grade(safeDiscard, { kind: 'safe_discard', tile: '3m' }).result).toBe('wrong');
	});

	it('winning_tiles: exactly the waits is correct, in any order', () => {
		expect(grade(winningTiles, { kind: 'winning_tiles', tiles: ['6m', '3m'] }).result).toBe(
			'correct'
		);
	});

	it('winning_tiles: a strict subset of the waits is partial', () => {
		expect(grade(winningTiles, { kind: 'winning_tiles', tiles: ['3m'] }).result).toBe('partial');
	});

	it('winning_tiles: any non-wait, or nothing, is wrong', () => {
		expect(grade(winningTiles, { kind: 'winning_tiles', tiles: ['3m', '6m', '9m'] }).result).toBe(
			'wrong'
		);
		expect(grade(winningTiles, { kind: 'winning_tiles', tiles: ['9m'] }).result).toBe('wrong');
		expect(grade(winningTiles, { kind: 'winning_tiles', tiles: [] }).result).toBe('wrong');
	});

	it('count_faan: the key total is correct, any other wrong', () => {
		expect(grade(countFaan, { kind: 'count_faan', faan: 3 }).result).toBe('correct');
		expect(grade(countFaan, { kind: 'count_faan', faan: 4 }).result).toBe('wrong');
	});

	it('an answer for another kind is wrong', () => {
		expect(grade(countFaan, { kind: 'best_discard', tile: 'z5' }).result).toBe('wrong');
	});
});
