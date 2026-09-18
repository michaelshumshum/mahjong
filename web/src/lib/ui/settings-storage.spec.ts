import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { AutoArm, ClientPrefs } from './Settings.svelte';
import {
	AUTO_ARM_STORAGE_KEY,
	CLIENT_PREFS_STORAGE_KEY,
	DISPLAY_NAME_STORAGE_KEY,
	loadAutoArm,
	loadClientPrefs,
	loadDisplayName,
	saveAutoArm,
	saveClientPrefs,
	saveDisplayName
} from './settings-storage';

// In-memory fake -- this file runs under the 'server' vitest project (plain node, no jsdom/
// browser globals per web/AGENTS.md's *.svelte.spec.ts note), so `localStorage` doesn't exist
// as a global until a test installs one on `globalThis`.
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
			const prefs: ClientPrefs = { soundEnabled: false, motion: 'reduced' };
			saveClientPrefs(prefs);
			expect(loadClientPrefs()).toEqual(prefs);
		});

		it('returns null when nothing has been stored', () => {
			expect(loadClientPrefs()).toBeNull();
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
				removeItem: () => {}
			};
			(globalThis as { localStorage?: Storage }).localStorage = throwing;

			expect(() => saveClientPrefs({ soundEnabled: true, motion: 'full' })).not.toThrow();
			expect(() => saveAutoArm({ noCalls: true, autoPassChow: true })).not.toThrow();
			expect(() => saveDisplayName('Alice')).not.toThrow();
			expect(loadClientPrefs()).toBeNull();
			expect(loadAutoArm()).toBeNull();
			expect(loadDisplayName()).toBeNull();
		});

		it('save and load never throw when localStorage is undefined entirely', () => {
			delete (globalThis as { localStorage?: Storage }).localStorage;

			expect(() => saveClientPrefs({ soundEnabled: true, motion: 'full' })).not.toThrow();
			expect(() => saveAutoArm({ noCalls: true, autoPassChow: true })).not.toThrow();
			expect(() => saveDisplayName('Alice')).not.toThrow();
			expect(loadClientPrefs()).toBeNull();
			expect(loadAutoArm()).toBeNull();
			expect(loadDisplayName()).toBeNull();
		});
	});
});
