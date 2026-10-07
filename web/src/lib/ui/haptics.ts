/** `navigator.vibrate`, mobile only (coarse pointer), feature-detected to a no-op elsewhere.
 * One pulse per call, driven by a transient signal -- never a ticker. */
export function vibrate(ms: number): void {
	if (typeof navigator === 'undefined' || typeof navigator.vibrate !== 'function') return;
	if (typeof matchMedia !== 'function' || !matchMedia('(pointer: coarse)').matches) return;
	navigator.vibrate(ms);
}
