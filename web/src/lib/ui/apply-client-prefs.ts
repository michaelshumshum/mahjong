import type { ClientPrefs } from './client-prefs';
import { applyMotionPref } from './motion';
import { applySoundPrefs } from './sfx';
import { applyTileSize } from './tile-size';

/** Pushes every pref with a side effect outside the Settings dialog into effect: on load (root
 * layout) and on each change (lobby and table Settings). */
export function applyClientPrefs(prefs: ClientPrefs): void {
	applyMotionPref(prefs.motion);
	applyTileSize(prefs.tileSize);
	applySoundPrefs(prefs);
}
