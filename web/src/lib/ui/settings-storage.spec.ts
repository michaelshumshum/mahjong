import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { AutoArm, ClientPrefs } from './Settings.svelte';
import {
	AUTO_ARM_STORAGE_KEY,
	CLIENT_PREFS_STORAGE_KEY,
	DISPLAY_NAME_STORAGE_KEY,
	PRACTICE_SETUP_STORAGE_KEY,
	ONBOARDING_STORAGE_KEY,
	loadOnboarding,
	saveOnboarding,
	loadPracticeSetup,
	savePracticeSetup,
	TABLE_CREDS_TTL_MS,
	clearSeatForTable,
	clearSecretForTable,
	cleanupStaleTableCredentials,
	hasJoinedTable,
	loadAutoArm,
	loadClientPrefs,
	loadDisplayName,
	loadSeatForTable,
	loadSecretForTable,
	saveAutoArm,
	saveClientPrefs,
	saveDisplayName,
	saveSeatForTable,
	saveSecretForTable
} from './settings-storage';

// In-memory fake -- this file runs under the 'server' vitest project (plain node, no jsdom),
// so `localStorage` doesn't exist as a global until a test installs one.
class FakeStorage implements Storage {
	#data = new Map<string, string>();
	get length(): number {
		return this.#data.size;
	}
	clear(): void {
		this.#data.clear();
	}
	getItem(key: string): string | null {
		return this.#data.has(key) ? this.#data.get(key)! : null;
	}
	key(index: number): string | null {
		return [...this.#data.keys()][index] ?? null;
	}
	removeItem(key: string): void {
		this.#data.delete(key);
	}
	setItem(key: string, value: string): void {
		this.#data.set(key, value);
	}
}

describe('settings-storage', () => {
	let originalLocalStorage: Storage | undefined;

	beforeEach(() => {
		originalLocalStorage = (globalThis as { localStorage?: Storage }).localStorage;
		(globalThis as { localStorage?: Storage }).localStorage = new FakeStorage();
	});

	afterEach(() => {
		if (originalLocalStorage === undefined) {
			delete (globalThis as { localStorage?: Storage }).localStorage;
		} else {
			(globalThis as { localStorage?: Storage }).localStorage = originalLocalStorage;
		}
	});

	describe('clientPrefs', () => {
		it('round-trips a saved value', () => {
			const prefs: ClientPrefs = {
				soundEnabled: false,
				motion: 'reduced',
				discardMode: 'one-tap',
				haptics: false,
				announceAllDiscards: true
			};
			saveClientPrefs(prefs);
			expect(loadClientPrefs()).toEqual(prefs);
		});

		it('returns null when nothing has been stored', () => {
			expect(loadClientPrefs()).toBeNull();
		});

		it('migrates a pre-discardMode stored value to the two-step default', () => {
			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({ soundEnabled: true, motion: 'system' })
			);
			expect(loadClientPrefs()).toEqual({
				soundEnabled: true,
				motion: 'system',
				discardMode: 'two-step',
				haptics: true,
				announceAllDiscards: false
			});
		});

		it('migrates a pre-haptics stored value to the haptics-on default', () => {
			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({ soundEnabled: true, motion: 'system', discardMode: 'one-tap' })
			);
			expect(loadClientPrefs()?.haptics).toBe(true);
		});

		it('keeps an explicit stored haptics: false rather than defaulting it', () => {
			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({
					soundEnabled: true,
					motion: 'system',
					discardMode: 'one-tap',
					haptics: false
				})
			);
			expect(loadClientPrefs()?.haptics).toBe(false);
		});

		it('migrates a pre-announcement stored value to announcing claim-relevant discards only', () => {
			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({
					soundEnabled: true,
					motion: 'system',
					discardMode: 'one-tap',
					haptics: false
				})
			);
			expect(loadClientPrefs()).toEqual({
				soundEnabled: true,
				motion: 'system',
				discardMode: 'one-tap',
				haptics: false,
				announceAllDiscards: false
			});
		});

		it('discards an invalid stored discardMode in favour of the default', () => {
			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({ soundEnabled: true, motion: 'system', discardMode: 'swipe' })
			);
			expect(loadClientPrefs()?.discardMode).toBe('two-step');
		});

		it('falls back to null on malformed JSON rather than throwing', () => {
			localStorage.setItem(CLIENT_PREFS_STORAGE_KEY, '{not json');
			expect(() => loadClientPrefs()).not.toThrow();
			expect(loadClientPrefs()).toBeNull();
		});

		it('falls back to null on a validly-parsed but wrong-shaped value', () => {
			localStorage.setItem(CLIENT_PREFS_STORAGE_KEY, JSON.stringify({ soundEnabled: 'yes' }));
			expect(loadClientPrefs()).toBeNull();

			localStorage.setItem(
				CLIENT_PREFS_STORAGE_KEY,
				JSON.stringify({ soundEnabled: true, motion: 'ludicrous' })
			);
			expect(loadClientPrefs()).toBeNull();
		});

		it('falls back to null on a stored primitive/array/null', () => {
			for (const bad of ['42', 'null', '[]', '"a string"']) {
				localStorage.setItem(CLIENT_PREFS_STORAGE_KEY, bad);
				expect(loadClientPrefs()).toBeNull();
			}
		});
	});

	describe('autoArm', () => {
		it('round-trips a saved value', () => {
			const autoArm: AutoArm = { noCalls: true, autoPassChow: false };
			saveAutoArm(autoArm);
			expect(loadAutoArm()).toEqual(autoArm);
		});

		it('returns null when nothing has been stored', () => {
			expect(loadAutoArm()).toBeNull();
		});

		it('falls back to null on malformed JSON rather than throwing', () => {
			localStorage.setItem(AUTO_ARM_STORAGE_KEY, 'undefined');
			expect(() => loadAutoArm()).not.toThrow();
			expect(loadAutoArm()).toBeNull();
		});

		it('falls back to null on a validly-parsed but wrong-shaped value', () => {
			localStorage.setItem(AUTO_ARM_STORAGE_KEY, JSON.stringify({ noCalls: true }));
			expect(loadAutoArm()).toBeNull();
		});
	});

	describe('practiceSetup', () => {
		it('round-trips a saved value', () => {
			savePracticeSetup({ 1: 'easy', 2: 'normal', 3: 'impossible' });
			expect(loadPracticeSetup()).toEqual({ 1: 'easy', 2: 'normal', 3: 'impossible' });
		});

		it('returns null when nothing has been stored', () => {
			expect(loadPracticeSetup()).toBeNull();
		});

		it('rejects an unknown difficulty or a missing seat', () => {
			localStorage.setItem(
				PRACTICE_SETUP_STORAGE_KEY,
				JSON.stringify({ 1: 'easy', 2: 'godlike', 3: 'normal' })
			);
			expect(loadPracticeSetup()).toBeNull();
			localStorage.setItem(PRACTICE_SETUP_STORAGE_KEY, JSON.stringify({ 1: 'easy', 2: 'normal' }));
			expect(loadPracticeSetup()).toBeNull();
		});
	});

	describe('onboarding', () => {
		it('round-trips a saved value', () => {
			saveOnboarding({ coachMarksDone: true });
			expect(loadOnboarding()).toEqual({ coachMarksDone: true });
		});

		it('falls back to null on a wrong-shaped value', () => {
			localStorage.setItem(ONBOARDING_STORAGE_KEY, JSON.stringify({ coachMarksDone: 'yes' }));
			expect(loadOnboarding()).toBeNull();
		});
	});

	describe('displayName', () => {
		it('round-trips a saved value', () => {
			saveDisplayName('Alice');
			expect(loadDisplayName()).toBe('Alice');
		});

		it('returns null when nothing has been stored', () => {
			expect(loadDisplayName()).toBeNull();
		});

		it('falls back to null on malformed JSON rather than throwing', () => {
			localStorage.setItem(DISPLAY_NAME_STORAGE_KEY, '{not json');
			expect(() => loadDisplayName()).not.toThrow();
			expect(loadDisplayName()).toBeNull();
		});

		it('falls back to null on a validly-parsed but wrong-shaped value', () => {
			localStorage.setItem(DISPLAY_NAME_STORAGE_KEY, JSON.stringify(42));
			expect(loadDisplayName()).toBeNull();
			localStorage.setItem(DISPLAY_NAME_STORAGE_KEY, JSON.stringify({ name: 'Alice' }));
			expect(loadDisplayName()).toBeNull();
		});
	});

	describe('seat and reconnect secret', () => {
		it('round-trips per-table seat and secret', () => {
			saveSeatForTable('abc123', 2);
			saveSecretForTable('abc123', 'shhh');
			expect(loadSeatForTable('abc123')).toBe(2);
			expect(loadSecretForTable('abc123')).toBe('shhh');
		});

		it('hasJoinedTable is true when a seat or secret is stored', () => {
			expect(hasJoinedTable('abc123')).toBe(false);
			saveSeatForTable('abc123', 2);
			expect(hasJoinedTable('abc123')).toBe(true);
			clearSeatForTable('abc123');
			expect(hasJoinedTable('abc123')).toBe(false);
			saveSecretForTable('abc123', 'shhh');
			expect(hasJoinedTable('abc123')).toBe(true);
		});

		it('hasJoinedTable is false for stale credentials', () => {
			const stale = Date.now() - TABLE_CREDS_TTL_MS - 1;
			localStorage.setItem('mahjong:seat:v2:old', JSON.stringify({ seat: 2, savedAt: stale }));
			expect(hasJoinedTable('old')).toBe(false);
		});

		it('keys are isolated per table', () => {
			saveSeatForTable('abc123', 2);
			saveSecretForTable('abc123', 'shhh');
			saveSeatForTable('xyz789', 0);
			saveSecretForTable('xyz789', 'other');
			expect(loadSeatForTable('abc123')).toBe(2);
			expect(loadSecretForTable('abc123')).toBe('shhh');
			expect(loadSeatForTable('xyz789')).toBe(0);
			expect(loadSecretForTable('xyz789')).toBe('other');
		});

		it('clear removes only the requested table', () => {
			saveSeatForTable('abc123', 2);
			saveSecretForTable('abc123', 'shhh');
			saveSeatForTable('xyz789', 0);
			saveSecretForTable('xyz789', 'other');
			clearSeatForTable('abc123');
			clearSecretForTable('abc123');
			expect(loadSeatForTable('abc123')).toBeNull();
			expect(loadSecretForTable('abc123')).toBeNull();
			expect(loadSeatForTable('xyz789')).toBe(0);
			expect(loadSecretForTable('xyz789')).toBe('other');
		});

		it('clear is a no-op when nothing is stored', () => {
			expect(() => clearSeatForTable('missing')).not.toThrow();
			expect(() => clearSecretForTable('missing')).not.toThrow();
		});

		it('returns null and clears stale credentials past the TTL', () => {
			const stale = Date.now() - TABLE_CREDS_TTL_MS - 1;
			localStorage.setItem('mahjong:seat:v2:old', JSON.stringify({ seat: 2, savedAt: stale }));
			localStorage.setItem(
				'mahjong:reconnectSecret:v2:old',
				JSON.stringify({ secret: 'shhh', savedAt: stale })
			);
			expect(loadSeatForTable('old')).toBeNull();
			expect(loadSecretForTable('old')).toBeNull();
			expect(localStorage.getItem('mahjong:seat:v2:old')).toBeNull();
			expect(localStorage.getItem('mahjong:reconnectSecret:v2:old')).toBeNull();
		});

		it('cleanup removes stale v2 credentials and legacy v1 keys', () => {
			const stale = Date.now() - TABLE_CREDS_TTL_MS - 1;
			localStorage.setItem('mahjong:seat:v2:stale', JSON.stringify({ seat: 2, savedAt: stale }));
			localStorage.setItem(
				'mahjong:reconnectSecret:v2:stale',
				JSON.stringify({ secret: 'shhh', savedAt: stale })
			);
			localStorage.setItem('mahjong:seat:v1:legacy', JSON.stringify(2));
			localStorage.setItem('mahjong:reconnectSecret:v1:legacy', JSON.stringify('shhh'));
			localStorage.setItem(
				'mahjong:seat:v2:fresh',
				JSON.stringify({ seat: 0, savedAt: Date.now() })
			);
			cleanupStaleTableCredentials();
			expect(localStorage.getItem('mahjong:seat:v2:stale')).toBeNull();
			expect(localStorage.getItem('mahjong:reconnectSecret:v2:stale')).toBeNull();
			expect(localStorage.getItem('mahjong:seat:v1:legacy')).toBeNull();
			expect(localStorage.getItem('mahjong:reconnectSecret:v1:legacy')).toBeNull();
			expect(localStorage.getItem('mahjong:seat:v2:fresh')).not.toBeNull();
		});

		it('cleanup is a no-op when localStorage is absent', () => {
			delete (globalThis as { localStorage?: Storage }).localStorage;
			expect(() => cleanupStaleTableCredentials()).not.toThrow();
		});
	});

	describe('graceful degradation when localStorage throws or is absent', () => {
		it('save and load never throw when getItem/setItem throw', () => {
			const throwing: Storage = {
				length: 0,
				clear: () => {},
				key: () => null,
				getItem: () => {
					throw new DOMException('blocked', 'SecurityError');
				},
				setItem: () => {
					throw new DOMException('blocked', 'SecurityError');
				},
				removeItem: () => {
					throw new DOMException('blocked', 'SecurityError');
				}
			};
			(globalThis as { localStorage?: Storage }).localStorage = throwing;

			expect(() =>
				saveClientPrefs({
					soundEnabled: true,
					motion: 'full',
					discardMode: 'two-step',
					haptics: true,
					announceAllDiscards: false
				})
			).not.toThrow();
			expect(() => saveAutoArm({ noCalls: true, autoPassChow: true })).not.toThrow();
			expect(() => saveDisplayName('Alice')).not.toThrow();
			expect(() => clearSeatForTable('x')).not.toThrow();
			expect(() => clearSecretForTable('x')).not.toThrow();
			expect(loadClientPrefs()).toBeNull();
			expect(loadAutoArm()).toBeNull();
			expect(loadDisplayName()).toBeNull();
		});

		it('save and load never throw when localStorage is undefined entirely', () => {
			delete (globalThis as { localStorage?: Storage }).localStorage;

			expect(() =>
				saveClientPrefs({
					soundEnabled: true,
					motion: 'full',
					discardMode: 'two-step',
					haptics: true,
					announceAllDiscards: false
				})
			).not.toThrow();
			expect(() => saveAutoArm({ noCalls: true, autoPassChow: true })).not.toThrow();
			expect(() => saveDisplayName('Alice')).not.toThrow();
			expect(() => clearSeatForTable('x')).not.toThrow();
			expect(() => clearSecretForTable('x')).not.toThrow();
			expect(loadClientPrefs()).toBeNull();
			expect(loadAutoArm()).toBeNull();
			expect(loadDisplayName()).toBeNull();
		});
	});
});
