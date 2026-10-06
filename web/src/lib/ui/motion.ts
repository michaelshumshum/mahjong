import type { MotionPref } from './Settings.svelte';

/** Mirrors the "Reduce motion" setting onto `html[data-motion]`, which `_a11y.scss`'s
 * `motion-ok`/`motion-reduced` mixins read. */
export function applyMotionPref(
	pref: MotionPref,
	root: HTMLElement = document.documentElement
): void {
	root.dataset.motion = pref;
}

/** Same resolution as the CSS mixins, for motion driven from JS (the mural canvas). */
export function isMotionReduced(root: HTMLElement = document.documentElement): boolean {
	const pref = root.dataset.motion;
	if (pref === 'reduced') return true;
	if (pref === 'full') return false;
	return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}
