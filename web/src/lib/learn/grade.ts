// lookup against the generated answer key only: the engine already graded every choice (ADR 0025),
// so nothing here knows a mahjong rule.

import type { Lesson } from './generated/lessons';
import type { Answer, Grade } from './types';

export function grade(lesson: Lesson, answer: Answer): Grade {
	if (answer.kind !== lesson.kind) return { result: 'wrong' };
	switch (lesson.kind) {
		case 'best_discard':
		case 'safe_discard':
			return {
				result: 'tile' in answer && lesson.key.correct.includes(answer.tile) ? 'correct' : 'wrong'
			};
		case 'winning_tiles': {
			if (!('tiles' in answer)) return { result: 'wrong' };
			const correct = new Set(lesson.key.correct);
			const picked = new Set(answer.tiles);
			if (picked.size === 0 || [...picked].some((tile) => !correct.has(tile))) {
				return { result: 'wrong' };
			}
			return { result: picked.size === correct.size ? 'correct' : 'partial' };
		}
		case 'count_faan':
			return {
				result: 'faan' in answer && answer.faan === lesson.key.correct ? 'correct' : 'wrong'
			};
	}
}
