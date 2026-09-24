import { SvelteSet } from 'svelte/reactivity';

// The mural background mounts once in the root layout and never unmounts on navigation, so its
// canvas doesn't tear down and restart every time between two mural routes. Pages toggle this
// shared flag on mount instead of rendering their own instance.
//
// A claim set, not a plain boolean: ApiConnectGate claims the mural while its own overlay is up,
// and releases it the same instant a newly-mounted page (lobby, tables, ...) claims it for
// itself -- both changes land in the same reactive flush, and a plain last-write-wins boolean
// left `visible` stuck on whichever of the two effects happened to rerun last (observed: stuck
// false even though a page below still wanted it). Keyed by claim, so two claimants transiently
// overlapping (one releasing as another claims) never drops through empty.
//
// `SvelteSet`, not a plain `Set` wrapped in `$state` -- `$state` only makes the *reference*
// reactive (reassignment), not a built-in Set/Map's own mutator methods; `.add()`/`.delete()` on
// a plain `$state(new Set())` silently never invalidate a `$derived` reading `.size` (observed:
// the set's real size was correct, `visible` stayed stuck at its first-ever computed value).
// `SvelteSet` from `svelte/reactivity` instruments those methods for exactly this case.
class MuralVisibility {
	#claims = new SvelteSet<symbol>();
	visible = $derived(this.#claims.size > 0);

	claim(token: symbol): void {
		this.#claims.add(token);
	}

	release(token: symbol): void {
		this.#claims.delete(token);
	}
}

export const muralVisibility = new MuralVisibility();

// call once from a page's <script> to claim mural visibility while mounted, releasing on
// unmount. `wanted` is a getter, not a boolean, so the claim can vary reactively while mounted.
export function claimMuralVisible(wanted: () => boolean = () => true): void {
	const token = Symbol();
	$effect(() => {
		if (!wanted()) return;
		muralVisibility.claim(token);
		return () => muralVisibility.release(token);
	});
}
