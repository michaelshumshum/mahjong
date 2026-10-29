import { describe, expect, it } from 'vitest';
import { viewFromClientState } from '$lib/table/live-view';
import { legalDiscardIds } from '$lib/table/legal-actions';
import discardWin from './generated/basics-discard-win.json';
import isolatedHonour from './generated/basics-isolated-honour.json';
import type { Lesson } from './generated/lessons';
import { puzzleState } from './puzzle-state';

describe('puzzleState', () => {
	it('seats you at 0 with the snapshot hand, every seat named', () => {
		const lesson = isolatedHonour as unknown as Lesson;
		const state = puzzleState(lesson);
		expect(state.seat).toBe(0);
		expect(state.ownHand).toEqual(lesson.snapshot.d.own_hand);
		expect(state.names.every((name) => typeof name === 'string' && name.length > 0)).toBe(true);
		expect(new Set(state.names).size).toBe(4);
	});

	it('projects to the table view, the drawn tile held apart and the hand discardable', () => {
		const state = puzzleState(isolatedHonour as unknown as Lesson);
		const live = viewFromClientState(state)!;
		expect(live.ownHand.drawnId).not.toBeNull();
		expect(live.ownHand.concealedIds).toHaveLength(13);
		expect(legalDiscardIds(state.legalActions).size).toBe(14);
	});

	it('marks the discard a claim puzzle wins on', () => {
		const state = puzzleState(discardWin as unknown as Lesson);
		const live = viewFromClientState(state)!;
		expect(live.view.lastDiscard?.seat).toBe(state.turn);
		// no live window id, so no claim buttons over the puzzle
		expect(live.view.claimWindow).toBeNull();
	});
});
