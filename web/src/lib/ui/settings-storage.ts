import type { AutoArm, ClientPrefs, MotionPref } from './Settings.svelte';

// Namespaced, versioned keys -- `v1` lets a future shape change fail closed (treated as
// missing, below) instead of crashing on an old stored shape.
export const CLIENT_PREFS_STORAGE_KEY = 'mahjong:clientPrefs:v1';
export const AUTO_ARM_STORAGE_KEY = 'mahjong:autoArm:v1';
export const DISPLAY_NAME_STORAGE_KEY = 'mahjong:displayName:v1';
const SEAT_STORAGE_KEY_PREFIX = 'mahjong:seat:v1:';

const MOTION_PREFS: readonly MotionPref[] = ['system', 'reduced', 'full'];

function isMotionPref(value: unknown): value is MotionPref {
	return typeof value === 'string' && (MOTION_PREFS as readonly string[]).includes(value);
}

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

/** `localStorage` can throw (private browsing, blocked/full storage) or simply not exist
 * (SSR, a test environment) -- every read/write is wrapped so a storage failure never breaks
 * the page; callers always get a usable value (`load*` returns `null`, treated as "use the
 * default") rather than an exception. */
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
	return load(CLIENT_PREFS_STORAGE_KEY, isClientPrefs);
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

/** The client-chosen guest display name (docs/02-protocol.md's Auth section, M5), sent once on
 * `join`. Not validated here beyond "is a string" -- the server trims/caps/defaults it
 * (`JoinPayload.name`), so this is purely "what the player typed last," not a verified value. */
export function loadDisplayName(): string | null {
	return load(DISPLAY_NAME_STORAGE_KEY, isDisplayName);
}

export function saveDisplayName(name: string): void {
	writeRaw(DISPLAY_NAME_STORAGE_KEY, JSON.stringify(name));
}

function isSeat(value: unknown): value is number {
	return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= 3;
}

/** Which seat this browser last held in a given room, keyed per-room since a seat number only
 * means something relative to one room's `Room.seats`. Lets a page reload resume via
 * `hello{seat}` (docs/02-protocol.md §5) instead of falling back to `join`, which fails with
 * `room_full` once all four seats are already bound -- the bug this persistence exists to fix. */
export function loadSeatForRoom(roomId: string): number | null {
	return load(SEAT_STORAGE_KEY_PREFIX + roomId, isSeat);
}

export function saveSeatForRoom(roomId: string, seat: number): void {
	writeRaw(SEAT_STORAGE_KEY_PREFIX + roomId, JSON.stringify(seat));
}
