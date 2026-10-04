import { SvelteSet } from 'svelte/reactivity';

// shared claim-counted mural-visibility flag; a plain boolean or a $state-wrapped Set both lose
// claims under concurrent claim/release -- see docs/frontend.md §2's "Shared across routes" for why SvelteSet.
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
