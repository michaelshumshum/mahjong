import type { MotionPref } from './client-prefs';

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

/** A JS-driven duration (`animate:flip`, `transition:`) that collapses to 0ms under reduced
 * motion, same resolution as the CSS mixins -- never a per-frame ticker, just the one number. */
export function motionMs(ms: number, root: HTMLElement = document.documentElement): number {
	return isMotionReduced(root) ? 0 : ms;
}
