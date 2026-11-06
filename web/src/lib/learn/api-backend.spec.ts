import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

import { ApiBackend, lessonFromWire, lessonToWire, uploadBody, type LearnApi } from './api-backend';
import type { LearnWire } from '$lib/net/learn-api';
import { ONBOARDING_STORAGE_KEY } from '$lib/ui/settings-storage';

const PUZZLE = 'basics-isolated-honour';
const TUTORIAL = 'basics-tutorial';
const T0 = Date.UTC(2026, 10, 1, 12);

function fakeApi() {
	return {
		fetchLearn: vi.fn<LearnApi['fetchLearn']>(),
		putLesson: vi.fn<LearnApi['putLesson']>().mockResolvedValue(undefined),
		putEndless: vi.fn<LearnApi['putEndless']>().mockResolvedValue(undefined),
		patchPrefs: vi.fn<LearnApi['patchPrefs']>().mockResolvedValue(undefined),
		importLearn: vi.fn<LearnApi['importLearn']>()
	};
}

const SERVER: LearnWire = {
	progress: {
		[PUZZLE]: {
			solved: true,
			attempts: 3,
			solved_at: new Date(T0).toISOString(),
			step: null,
			imported: false
		},
		'no-longer-a-lesson': { solved: true, attempts: 1, imported: false }
	},
	endless: { count_faan: { streak: 2, best: 5, solved: 9, imported: true } },
	prefs: { learn_band: 'advanced' }
};

let writes: string[];
beforeEach(() => {
	writes = [];
	const data = new Map<string, string>();
	vi.stubGlobal('localStorage', {
		getItem: (key: string) => data.get(key) ?? null,
		setItem: (key: string, value: string) => {
			writes.push(key);
			data.set(key, value);
		},
		removeItem: (key: string) => void data.delete(key)
	});
});
afterEach(() => vi.unstubAllGlobals());

describe('wire shapes', () => {
	it('round-trips a lesson entry', () => {
		const entry = { solved: true, attempts: 2, solvedAt: T0, step: 4 };
		expect(lessonToWire(entry)).toEqual({
			solved: true,
			attempts: 2,
			solved_at: '2026-11-01T12:00:00.000Z',
			step: 4
		});
		expect(lessonFromWire(lessonToWire(entry))).toEqual(entry);
		expect(lessonFromWire({ solved: false, attempts: 0, solved_at: null, step: null })).toEqual({
			solved: false,
			attempts: 0
		});
	});

	it('builds the upload from both keys and the coach marks', () => {
		const body = uploadBody(
			{ [TUTORIAL]: { solved: false, attempts: 0, step: 3 } },
			{ band: 'intermediate', scores: { winning_tiles: { streak: 1, best: 2, solved: 3 } } },
			{ coachMarksDone: true }
		);
		expect(body).toEqual({
			progress: { [TUTORIAL]: { solved: false, attempts: 0, solved_at: null, step: 3 } },
			endless: { winning_tiles: { streak: 1, best: 2, solved: 3 } },
			prefs: { learn_band: 'intermediate', coach_marks_done: true }
		});
		// never saved: no band to send
		expect(uploadBody({}, null, null).prefs).toEqual({});
	});
});

describe('ApiBackend', () => {
	it('reads the account copy, known lessons only', () => {
		const backend = new ApiBackend(fakeApi());
		expect(backend.endless().band).toBe('beginner');
		backend.fill(SERVER);
		expect(backend.progress()).toEqual({ [PUZZLE]: { solved: true, attempts: 3, solvedAt: T0 } });
		expect(backend.endless()).toEqual({
			band: 'advanced',
			scores: { count_faan: { streak: 2, best: 5, solved: 9 } }
		});
	});

	it('writes to the api, never to localStorage', () => {
		const api = fakeApi();
		const backend = new ApiBackend(api);
		backend.fill(SERVER);
		backend.putLesson(TUTORIAL, { solved: false, attempts: 0, step: 2 });
		backend.putEndlessScore('safe_discard', { streak: 1, best: 1, solved: 1 });
		backend.putBand('intermediate');
		backend.putOnboarding({ coachMarksDone: true });
		expect(api.putLesson).toHaveBeenCalledWith(TUTORIAL, {
			solved: false,
			attempts: 0,
			solved_at: null,
			step: 2
		});
		expect(api.putEndless).toHaveBeenCalledWith('safe_discard', { streak: 1, best: 1, solved: 1 });
		expect(api.patchPrefs).toHaveBeenCalledWith({ learn_band: 'intermediate' });
		expect(api.patchPrefs).toHaveBeenCalledWith({ coach_marks_done: true });
		expect(backend.progress()[TUTORIAL].step).toBe(2);
		expect(backend.endless().band).toBe('intermediate');
		expect(backend.onboarding()).toEqual({ coachMarksDone: true });
		expect(writes).toEqual([]);
	});

	it('keeps writes made before the account copy arrived', () => {
		const backend = new ApiBackend(fakeApi());
		backend.putLesson(PUZZLE, { solved: false, attempts: 1 });
		backend.putEndlessScore('count_faan', { streak: 0, best: 0, solved: 0 });
		backend.putBand('beginner');
		backend.fill(SERVER);
		expect(backend.progress()[PUZZLE]).toEqual({ solved: true, attempts: 3, solvedAt: T0 });
		expect(backend.endless()).toEqual({
			band: 'beginner',
			scores: { count_faan: { streak: 0, best: 5, solved: 9 } }
		});
	});

	it("falls back to this browser's coach marks until the account has its own", () => {
		localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({ coachMarksDone: true }));
		const backend = new ApiBackend(fakeApi());
		backend.fill(SERVER);
		expect(backend.onboarding()).toEqual({ coachMarksDone: true });
		backend.fill({ ...SERVER, prefs: { coach_marks_done: false } });
		expect(backend.onboarding()).toEqual({ coachMarksDone: false });
	});

	it('swallows a failed write into onError', async () => {
		const api = fakeApi();
		api.putLesson.mockRejectedValue(new Error('500'));
		const onError = vi.fn();
		new ApiBackend(api, onError).putLesson(PUZZLE, { solved: false, attempts: 1 });
		await vi.waitFor(() => expect(onError).toHaveBeenCalled());
	});
});
