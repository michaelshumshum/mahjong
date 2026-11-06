import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('$env/dynamic/public', () => ({ env: {} }));

import type { LearnApi } from './api-backend';
import { LearnSync } from './learn-sync.svelte';
import { loadProgress, saveAttempt } from './progress';
import { localBackend, progressStore } from './progress-store';
import type { LearnWire } from '$lib/net/learn-api';
import {
	LEARN_ENDLESS_STORAGE_KEY,
	LEARN_PROGRESS_STORAGE_KEY,
	LEARN_UPLOAD_DECLINED_STORAGE_KEY
} from '$lib/ui/settings-storage';

const PUZZLE = 'basics-isolated-honour';
const OTHER = 'basics-two-sided-wait';
const EMPTY: LearnWire = { progress: {}, endless: {}, prefs: {} };
const MERGED: LearnWire = {
	progress: { [PUZZLE]: { solved: true, attempts: 2, imported: true } },
	endless: {},
	prefs: {}
};

function fakeApi() {
	return {
		fetchLearn: vi.fn<LearnApi['fetchLearn']>().mockResolvedValue(EMPTY),
		putLesson: vi.fn<LearnApi['putLesson']>().mockResolvedValue(undefined),
		putEndless: vi.fn<LearnApi['putEndless']>().mockResolvedValue(undefined),
		patchPrefs: vi.fn<LearnApi['patchPrefs']>().mockResolvedValue(undefined),
		importLearn: vi.fn<LearnApi['importLearn']>().mockResolvedValue(MERGED)
	};
}

function seedGuestProgress(): void {
	localStorage.setItem(
		LEARN_PROGRESS_STORAGE_KEY,
		JSON.stringify({ [PUZZLE]: { solved: true, attempts: 2, solvedAt: 1 } })
	);
	localStorage.setItem(LEARN_ENDLESS_STORAGE_KEY, JSON.stringify({ band: 'advanced', scores: {} }));
}

let sync: LearnSync;
let api: ReturnType<typeof fakeApi>;
beforeEach(() => {
	localStorage.clear();
	api = fakeApi();
	sync = new LearnSync(api);
});
afterEach(() => {
	sync.guest();
	localStorage.clear();
});

describe('LearnSync', () => {
	it('switches to the api when signed in and back to localStorage as a guest', async () => {
		await sync.signedIn('u1');
		expect(progressStore()).not.toBe(localBackend);
		saveAttempt(OTHER, false);
		expect(api.putLesson).toHaveBeenCalledWith(OTHER, expect.objectContaining({ attempts: 1 }));
		expect(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)).toBeNull();
		sync.guest();
		expect(progressStore()).toBe(localBackend);
		expect(loadProgress()).toEqual({});
	});

	it('offers nothing without guest progress', async () => {
		await sync.signedIn('u1');
		expect(sync.offer).toBe('none');
	});

	it('uploads once, then deletes both keys', async () => {
		seedGuestProgress();
		await sync.signedIn('u1');
		expect(sync.offer).toBe('open');
		await sync.upload();
		expect(api.importLearn).toHaveBeenCalledWith({
			progress: {
				[PUZZLE]: {
					solved: true,
					attempts: 2,
					solved_at: '1970-01-01T00:00:00.001Z',
					step: null
				}
			},
			endless: {},
			prefs: { learn_band: 'advanced' }
		});
		expect(sync.offer).toBe('none');
		expect(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)).toBeNull();
		expect(localStorage.getItem(LEARN_ENDLESS_STORAGE_KEY)).toBeNull();
		expect(loadProgress()[PUZZLE]).toEqual({ solved: true, attempts: 2 });
	});

	it('keeps both keys when the upload fails, and offers again next sign-in', async () => {
		seedGuestProgress();
		api.importLearn.mockRejectedValue(new Error('500'));
		await sync.signedIn('u1');
		await sync.upload();
		expect(sync.offer).toBe('failed');
		expect(localStorage.getItem(LEARN_PROGRESS_STORAGE_KEY)).not.toBeNull();
		expect(localStorage.getItem(LEARN_ENDLESS_STORAGE_KEY)).not.toBeNull();
		sync.decline();
		sync.guest();
		await sync.signedIn('u1');
		expect(sync.offer).toBe('open');
	});

	it('remembers "not now" until sign-out', async () => {
		seedGuestProgress();
		await sync.signedIn('u1');
		sync.decline();
		expect(localStorage.getItem(LEARN_UPLOAD_DECLINED_STORAGE_KEY)).toBe('"u1"');
		const reload = new LearnSync(api);
		await reload.signedIn('u1');
		expect(reload.offer).toBe('none');
		reload.guest();
		expect(localStorage.getItem(LEARN_UPLOAD_DECLINED_STORAGE_KEY)).toBeNull();
		await reload.signedIn('u1');
		expect(reload.offer).toBe('open');
	});

	it('bumps version when the account copy arrives', async () => {
		const before = sync.version;
		await sync.signedIn('u1');
		expect(sync.version).toBeGreaterThan(before + 1);
	});
});
