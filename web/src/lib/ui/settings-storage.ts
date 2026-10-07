import type { AutoArm, ClientPrefs, DiscardMode, MotionPref } from './Settings.svelte';
import type { PracticeDifficulty } from '$lib/net/lobby';

// Namespaced, versioned keys -- `v1` lets a future shape change fail closed (treated as
// missing, below) instead of crashing on an old stored shape.
export const CLIENT_PREFS_STORAGE_KEY = 'mahjong:clientPrefs:v1';
export const AUTO_ARM_STORAGE_KEY = 'mahjong:autoArm:v1';
export const DISPLAY_NAME_STORAGE_KEY = 'mahjong:displayName:v1';
export const PRACTICE_SETUP_STORAGE_KEY = 'mahjong:practiceSetup:v1';
const SEAT_STORAGE_KEY_PREFIX = 'mahjong:seat:v2:';
const RECONNECT_SECRET_STORAGE_KEY_PREFIX = 'mahjong:reconnectSecret:v2:';

/** How long a per-table reconnect credential stays in `localStorage` -- a day covers a long
 * session's reload/return, and stops abandoned tables from leaving secrets behind forever. */
export const TABLE_CREDS_TTL_MS = 24 * 60 * 60 * 1000;

const MOTION_PREFS: readonly MotionPref[] = ['system', 'reduced', 'full'];
const DISCARD_MODES: readonly DiscardMode[] = ['two-step', 'one-tap'];
const DEFAULT_DISCARD_MODE: DiscardMode = 'two-step';

function isMotionPref(value: unknown): value is MotionPref {
	return typeof value === 'string' && (MOTION_PREFS as readonly string[]).includes(value);
}

function isDiscardMode(value: unknown): value is DiscardMode {
	return typeof value === 'string' && (DISCARD_MODES as readonly string[]).includes(value);
}

// only the fields that have always existed are required -- `discardMode` is newer and is
// migrated (defaulted) in `loadClientPrefs` below, not discarded along with the whole object.
export function isClientPrefs(value: unknown): value is ClientPrefs {
	if (typeof value !== 'object' || value === null) return false;
	const v = value as Record<string, unknown>;
	return typeof v.soundEnabled === 'boolean' && isMotionPref(v.motion);
}

export function isAutoArm(value: unknown): value is AutoArm {
	if (typeof value !== 'object' || value === null) return false;
	const v = value as Record<string, unknown>;
	return typeof v.noCalls === 'boolean' && typeof v.autoPassChow === 'boolean';
}

/** `localStorage` can throw (private browsing, blocked/full storage) or not exist (SSR) --
 * every read/write is wrapped so a failure never breaks the page. */
function readRaw(key: string): string | null {
	try {
		if (typeof localStorage === 'undefined') return null;
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

function writeRaw(key: string, value: string): void {
	try {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem(key, value);
	} catch {
		// storage unavailable/full/blocked -- the in-memory value still works this session
	}
}

function clearRaw(key: string): void {
	try {
		if (typeof localStorage === 'undefined') return;
		localStorage.removeItem(key);
	} catch {
		// storage unavailable/blocked -- nothing to clear anyway
	}
}

function load<T>(key: string, isValid: (value: unknown) => value is T): T | null {
	const raw = readRaw(key);
	if (raw === null) return null;
	try {
		const parsed: unknown = JSON.parse(raw);
		return isValid(parsed) ? parsed : null;
	} catch {
		return null; // corrupted JSON -- fall back to defaults, don't throw
	}
}

export function loadClientPrefs(): ClientPrefs | null {
	const raw = load(CLIENT_PREFS_STORAGE_KEY, isClientPrefs);
	if (raw === null) return null;
	const rawDiscardMode = (raw as unknown as Record<string, unknown>).discardMode;
	return {
		...raw,
		discardMode: isDiscardMode(rawDiscardMode) ? rawDiscardMode : DEFAULT_DISCARD_MODE
	};
}

export function saveClientPrefs(prefs: ClientPrefs): void {
	writeRaw(CLIENT_PREFS_STORAGE_KEY, JSON.stringify(prefs));
}

export function loadAutoArm(): AutoArm | null {
	return load(AUTO_ARM_STORAGE_KEY, isAutoArm);
}

export function saveAutoArm(autoArm: AutoArm): void {
	writeRaw(AUTO_ARM_STORAGE_KEY, JSON.stringify(autoArm));
}

function isDisplayName(value: unknown): value is string {
	return typeof value === 'string';
}

/** The client-chosen guest display name, sent once on `join`. Not validated here beyond "is a
 * string" -- the server trims/caps/defaults it, so this is just what the player typed last. */
export function loadDisplayName(): string | null {
	return load(DISPLAY_NAME_STORAGE_KEY, isDisplayName);
}

export function saveDisplayName(name: string): void {
	writeRaw(DISPLAY_NAME_STORAGE_KEY, JSON.stringify(name));
}

/** Bot difficulty per relative seat (1 right, 2 across, 3 left) of the last practice table. */
export type PracticeSetup = Record<1 | 2 | 3, PracticeDifficulty>;

const PRACTICE_DIFFICULTIES: readonly PracticeDifficulty[] = ['easy', 'normal', 'impossible'];

export function isPracticeSetup(value: unknown): value is PracticeSetup {
	if (typeof value !== 'object' || value === null) return false;
	const v = value as Record<string, unknown>;
	return [1, 2, 3].every(
		(seat) =>
			typeof v[seat] === 'string' &&
			(PRACTICE_DIFFICULTIES as readonly string[]).includes(v[seat] as string)
	);
}

/** Last practice setup -- prefills the practice dialog and drives game-end "Play again". */
export function loadPracticeSetup(): PracticeSetup | null {
	return load(PRACTICE_SETUP_STORAGE_KEY, isPracticeSetup);
}

export function savePracticeSetup(setup: PracticeSetup): void {
	writeRaw(PRACTICE_SETUP_STORAGE_KEY, JSON.stringify(setup));
}

interface StoredSeat {
	seat: number;
	savedAt: number;
}

function isStoredSeat(value: unknown): value is StoredSeat {
	if (typeof value !== 'object' || value === null) return false;
	const v = value as Record<string, unknown>;
	return (
		typeof v.seat === 'number' &&
		Number.isInteger(v.seat) &&
		v.seat >= 0 &&
		v.seat <= 3 &&
		typeof v.savedAt === 'number' &&
		Number.isFinite(v.savedAt)
	);
}

/** Which seat this browser last held in a given table. Lets a page reload resume via
 * `hello{seat}` instead of `join`, which fails with `table_full` once all seats are bound. */
export function loadSeatForTable(tableId: string): number | null {
	const raw = load<StoredSeat>(SEAT_STORAGE_KEY_PREFIX + tableId, isStoredSeat);
	if (raw === null) return null;
	if (Date.now() - raw.savedAt > TABLE_CREDS_TTL_MS) {
		clearSeatForTable(tableId);
		return null;
	}
	return raw.seat;
}

export function saveSeatForTable(tableId: string, seat: number): void {
	writeRaw(SEAT_STORAGE_KEY_PREFIX + tableId, JSON.stringify({ seat, savedAt: Date.now() }));
}

export function clearSeatForTable(tableId: string): void {
	clearRaw(SEAT_STORAGE_KEY_PREFIX + tableId);
}

interface StoredReconnectSecret {
	secret: string;
	savedAt: number;
}

function isStoredReconnectSecret(value: unknown): value is StoredReconnectSecret {
	if (typeof value !== 'object' || value === null) return false;
	const v = value as Record<string, unknown>;
	return (
		typeof v.secret === 'string' &&
		v.secret.length > 0 &&
		typeof v.savedAt === 'number' &&
		Number.isFinite(v.savedAt)
	);
}

/** The per-seat reconnect credential `join`'s ack returns -- required on every later
 * `hello{seat, secret}` or the server refuses the reclaim. */
export function loadSecretForTable(tableId: string): string | null {
	const raw = load<StoredReconnectSecret>(
		RECONNECT_SECRET_STORAGE_KEY_PREFIX + tableId,
		isStoredReconnectSecret
	);
	if (raw === null) return null;
	if (Date.now() - raw.savedAt > TABLE_CREDS_TTL_MS) {
		clearSecretForTable(tableId);
		return null;
	}
	return raw.secret;
}

export function saveSecretForTable(tableId: string, secret: string): void {
	writeRaw(
		RECONNECT_SECRET_STORAGE_KEY_PREFIX + tableId,
		JSON.stringify({ secret, savedAt: Date.now() })
	);
}

export function clearSecretForTable(tableId: string): void {
	clearRaw(RECONNECT_SECRET_STORAGE_KEY_PREFIX + tableId);
}

/** True when this browser has a non-expired reconnect credential for the table, meaning the
 * player sat there earlier and can reclaim the seat instead of joining fresh. */
export function hasJoinedTable(tableId: string): boolean {
	return loadSeatForTable(tableId) !== null || loadSecretForTable(tableId) !== null;
}

/** Remove per-table seat/secret entries older than `maxAgeMs` (default `TABLE_CREDS_TTL_MS`)
 * and any legacy `v1` per-table keys. Safe to call on every app startup. */
export function cleanupStaleTableCredentials(maxAgeMs: number = TABLE_CREDS_TTL_MS): void {
	try {
		if (typeof localStorage === 'undefined') return;
		const now = Date.now();
		const keysToRemove: string[] = [];
		for (let i = 0; i < localStorage.length; i++) {
			const key = localStorage.key(i);
			if (key === null) continue;
			if (
				key.startsWith(SEAT_STORAGE_KEY_PREFIX) ||
				key.startsWith(RECONNECT_SECRET_STORAGE_KEY_PREFIX)
			) {
				const raw = localStorage.getItem(key);
				if (raw === null) continue;
				try {
					const parsed: unknown = JSON.parse(raw);
					const savedAt = (parsed as Record<string, unknown> | null)?.savedAt ?? null;
					if (
						typeof savedAt !== 'number' ||
						!Number.isFinite(savedAt) ||
						now - savedAt > maxAgeMs
					) {
						keysToRemove.push(key);
					}
				} catch {
					// corrupted -- drop it
					keysToRemove.push(key);
				}
			} else if (
				key.startsWith('mahjong:seat:v1:') ||
				key.startsWith('mahjong:reconnectSecret:v1:')
			) {
				keysToRemove.push(key);
			}
		}
		for (const key of keysToRemove) {
			localStorage.removeItem(key);
		}
	} catch {
		// storage unavailable/blocked -- ignore
	}
}
