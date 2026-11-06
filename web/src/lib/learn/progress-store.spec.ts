import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadEndless, saveEndlessBand, saveEndlessScore } from './endless';
import {
	localBackend,
	progressStore,
	useProgressBackend,
	type ProgressBackend
} from './progress-store';
import { loadProgress, saveAttempt, saveTutorialDone, saveTutorialStep } from './progress';
import {
	LEARN_ENDLESS_STORAGE_KEY,
	LEARN_PROGRESS_STORAGE_KEY,
	ONBOARDING_STORAGE_KEY
} from '$lib/ui/settings-storage';

const PUZZLE = 'basics-isolated-honour';
const TUTORIAL = 'basics-tutorial';

function memoryStorage(): Storage {
	const data = new Map<string, string>();
	return {
		get length() {
			return data.size;
		},
		clear: () => data.clear(),
		getItem: (key) => data.get(key) ?? null,
		key: (i) => [...data.keys()][i] ?? null,
		removeItem: (key) => void data.delete(key),
		setItem: (key, value) => void data.set(key, value)
	};
}

beforeEach(() => vi.stubGlobal('localStorage', memoryStorage()));
afterEach(() => {
	vi.unstubAllGlobals();
	useProgressBackend(localBackend);
});

describe('progress store', () => {
	it('defaults to localStorage, under the existing keys', () => {
		expect(progressStore()).toBe(localBackend);
		saveAttempt(PUZZLE, true);
		saveEndlessBand('advanced');
		saveEndlessScore('count_faan', () => ({ streak: 1, best: 1, solved: 1 }));
		saveTutorialDone(TUTORIAL);
		expect(JSON.parse(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)!)).toMatchObject({
			[PUZZLE]: { solved: true, attempts: 1 },
			[TUTORIAL]: { solved: true, attempts: 1 }
		});
		expect(JSON.parse(localStorage.getItem(LEARN_ENDLESS_STORAGE_KEY)!)).toEqual({
			band: 'advanced',
			scores: { count_faan: { streak: 1, best: 1, solved: 1 } }
		});
		expect(JSON.parse(localStorage.getItem(ONBOARDING_STORAGE_KEY) ?? 'null')).toBeNull();
	});

	it('drops unknown lesson ids on the next write', () => {
		localStorage.setItem(
			LEARN_PROGRESS_STORAGE_KEY,
			JSON.stringify({ gone: { solved: true, attempts: 1 } })
		);
		saveAttempt(PUZZLE, false);
		expect(Object.keys(JSON.parse(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)!))).toEqual([
			PUZZLE
		]);
	});

	it('sends each write to the chosen backend as one entry', () => {
		const lessons: [string, unknown][] = [];
		const fake: ProgressBackend = {
			...localBackend,
			progress: () => ({ [TUTORIAL]: { solved: false, attempts: 0, step: 2 } }),
			putLesson: (id, entry) => void lessons.push([id, entry]),
			endless: () => ({ band: 'intermediate', scores: {} }),
			putEndlessScore: vi.fn(),
			putBand: vi.fn()
		};
		useProgressBackend(fake);
		expect(loadProgress()[TUTORIAL].step).toBe(2);
		saveTutorialStep(TUTORIAL, 3);
		saveAttempt(PUZZLE, true);
		expect(lessons).toEqual([
			[TUTORIAL, { solved: false, attempts: 0, step: 3 }],
			[PUZZLE, expect.objectContaining({ solved: true, attempts: 1 })]
		]);
		expect(loadEndless().band).toBe('intermediate');
		saveEndlessScore('winning_tiles', (s) => ({ ...s, solved: 1, best: 1, streak: 1 }));
		expect(fake.putEndlessScore).toHaveBeenCalledWith('winning_tiles', {
			streak: 1,
			best: 1,
			solved: 1
		});
		saveEndlessBand('beginner');
		expect(fake.putBand).toHaveBeenCalledWith('beginner');
		expect(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)).toBeNull();
	});
});
