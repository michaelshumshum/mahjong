import { describe, expect, it } from 'vitest';
import { ORDERED_LESSONS } from './lessons';
import {
	continueTab,
	firstUnsolved,
	LESSON_IDS,
	nextUnsolved,
	recordAttempt,
	recordTutorialStep,
	solvedCount
} from './progress';

describe('learn progress', () => {
	it('knows every generated lesson id', () => {
		expect(LESSON_IDS.size).toBeGreaterThan(0);
		expect(LESSON_IDS.has('basics-isolated-honour')).toBe(true);
	});

	it('counts attempts and marks the first correct one solved', () => {
		let progress = recordAttempt({}, 'a', false, 100);
		expect(progress).toEqual({ a: { solved: false, attempts: 1 } });
		progress = recordAttempt(progress, 'a', true, 200);
		expect(progress).toEqual({
			a: { solved: true, attempts: 2, solvedAt: 200 }
		});
	});

	it('keeps a solved lesson solved, with its first solvedAt', () => {
		let progress = recordAttempt({}, 'a', true, 100);
		progress = recordAttempt(progress, 'a', false, 200);
		progress = recordAttempt(progress, 'a', true, 300);
		expect(progress.a).toEqual({ solved: true, attempts: 3, solvedAt: 100 });
	});

	it('does not mutate the progress it is given', () => {
		const before = { a: { solved: false, attempts: 1 } };
		recordAttempt(before, 'a', true, 100);
		expect(before).toEqual({ a: { solved: false, attempts: 1 } });
	});

	it('counts solved lessons among the given ids', () => {
		const progress = {
			a: { solved: true, attempts: 1 },
			b: { solved: false, attempts: 2 },
			c: { solved: true, attempts: 1 }
		};
		expect(solvedCount(progress, ['a', 'b', 'd'])).toBe(1);
	});

	it('keeps a tutorial step, and clears it with null', () => {
		let progress = recordTutorialStep({}, 't', 4);
		expect(progress).toEqual({ t: { solved: false, attempts: 0, step: 4 } });
		progress = recordTutorialStep(recordAttempt(progress, 't', true, 100), 't', null);
		expect(progress).toEqual({
			t: { solved: true, attempts: 1, solvedAt: 100 }
		});
	});

	it('finds the first unsolved lesson in index order, skipping attempted-but-unsolved ones', () => {
		expect(firstUnsolved({})).toEqual(ORDERED_LESSONS[0]);
		const [first, second, third] = ORDERED_LESSONS;
		expect(firstUnsolved({ [first.id]: { solved: true, attempts: 1 } })).toEqual(second);
		expect(
			firstUnsolved({
				[first.id]: { solved: true, attempts: 1 },
				[third.id]: { solved: true, attempts: 1 },
				[second.id]: { solved: false, attempts: 3 }
			})
		).toEqual(second);
	});

	it('crosses tracks and returns null once everything is solved', () => {
		const basics = ORDERED_LESSONS.filter((lesson) => lesson.track === 'basics');
		const solved = (lessons: readonly { id: string }[]) =>
			Object.fromEntries(lessons.map((l) => [l.id, { solved: true, attempts: 1 }]));
		expect(firstUnsolved(solved(basics))?.track).toBe('waits');
		expect(firstUnsolved(solved(ORDERED_LESSONS))).toBeNull();
	});

	it("opens the index on the first unsolved lesson's track, endless once all are solved", () => {
		const solved = (lessons: readonly { id: string }[]) =>
			Object.fromEntries(lessons.map((l) => [l.id, { solved: true, attempts: 1 }]));
		expect(continueTab({})).toBe('basics');
		const basics = ORDERED_LESSONS.filter((lesson) => lesson.track === 'basics');
		expect(continueTab(solved(basics))).toBe('waits');
		expect(continueTab(solved(ORDERED_LESSONS))).toBe('endless');
	});

	describe('nextUnsolved', () => {
		const solved = (...ids: string[]) =>
			Object.fromEntries(ids.map((id) => [id, { solved: true, attempts: 1 }]));
		const [a, b, c, d] = ['a', 'b', 'c', 'd'].map(
			(id) => ({ ...ORDERED_LESSONS[0], id }) as (typeof ORDERED_LESSONS)[number]
		);
		const lessons = [a, b, c, d];

		it('takes the next unsolved lesson after the current one', () => {
			expect(nextUnsolved({}, 'a', lessons)).toEqual(b);
			expect(nextUnsolved(solved('b'), 'a', lessons)).toEqual(c);
			// attempted but unsolved still counts as unsolved
			expect(nextUnsolved({ b: { solved: false, attempts: 2 } }, 'a', lessons)).toEqual(b);
		});

		it('wraps round to an earlier unsolved lesson, never the current one', () => {
			expect(nextUnsolved(solved('d'), 'c', lessons)).toEqual(a);
			expect(nextUnsolved({}, 'd', lessons)).toEqual(a);
			expect(nextUnsolved(solved('a', 'b', 'd'), 'c', lessons)).toBeNull();
		});

		it('returns null once every lesson is solved', () => {
			expect(nextUnsolved(solved('a', 'b', 'c', 'd'), 'b', lessons)).toBeNull();
		});

		it('starts from the top for an id off the list', () => {
			expect(nextUnsolved(solved('a'), 'endless-1', lessons)).toEqual(b);
		});

		it('walks the real index order by default', () => {
			expect(nextUnsolved({}, ORDERED_LESSONS[0].id)).toEqual(ORDERED_LESSONS[1]);
		});
	});
});
