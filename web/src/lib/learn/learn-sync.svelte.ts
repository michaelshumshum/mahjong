// follows the account session: a guest reads and writes localStorage, a signed-in player the
// API (ADR 0028 "Learn progress: guest vs signed in"), plus the one-time upload offer.

import { ApiBackend, uploadBody, type LearnApi } from './api-backend';
import { LESSON_IDS } from './lessons';
import { localBackend, useProgressBackend } from './progress-store';
import * as learnApi from '$lib/net/learn-api';
import {
	clearLearnStorage,
	hasLearnEndless,
	loadLearnEndless,
	loadLearnProgress,
	loadOnboarding,
	loadUploadDeclined,
	saveUploadDeclined
} from '$lib/ui/settings-storage';

// none: nothing to offer; open: asking; failed: the upload failed, local copy kept
export type UploadOffer = 'none' | 'open' | 'uploading' | 'failed';

function hasGuestProgress(): boolean {
	return (
		Object.keys(loadLearnProgress(LESSON_IDS)).length > 0 ||
		Object.keys(loadLearnEndless().scores).length > 0
	);
}

export class LearnSync {
	/** Bumped whenever the backend or its data changes: pages that read progress on mount
	 * re-read on it. */
	version = $state(0);
	offer = $state<UploadOffer>('none');
	#accountId: string | null = null;
	#backend: ApiBackend | null = null;

	constructor(private readonly api: LearnApi = learnApi) {}

	async signedIn(accountId: string): Promise<void> {
		if (this.#accountId === accountId) return;
		this.#accountId = accountId;
		const backend = new ApiBackend(this.api);
		this.#backend = backend;
		useProgressBackend(backend);
		this.version++;
		try {
			backend.fill(await this.api.fetchLearn());
		} catch {
			// writes still reach the server, which merges them
		}
		if (this.#backend !== backend) return;
		this.version++;
		this.offer = hasGuestProgress() && loadUploadDeclined() !== accountId ? 'open' : 'none';
	}

	guest(): void {
		// signing out: the next sign-in on this device offers the upload again
		if (this.#accountId !== null) saveUploadDeclined(null);
		this.#accountId = null;
		this.#backend = null;
		useProgressBackend(localBackend);
		this.offer = 'none';
		this.version++;
	}

	/** Upload this browser's guest progress; on success its keys are deleted, on failure kept. */
	async upload(): Promise<void> {
		const backend = this.#backend;
		if (!backend || this.offer === 'uploading') return;
		this.offer = 'uploading';
		const body = uploadBody(
			loadLearnProgress(LESSON_IDS),
			hasLearnEndless() ? loadLearnEndless() : null,
			loadOnboarding()
		);
		try {
			const merged = await this.api.importLearn(body);
			clearLearnStorage();
			backend.fill(merged);
			this.offer = 'none';
			this.version++;
		} catch {
			this.offer = 'failed';
		}
	}

	/** Not now: kept on this device, offered again after the next sign-in. */
	decline(): void {
		if (this.#accountId !== null && this.offer === 'open') saveUploadDeclined(this.#accountId);
		this.offer = 'none';
	}
}

export const learnSync = new LearnSync();
