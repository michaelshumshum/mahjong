// The mural background (`TileMuralBackground.svelte`) mounts once in the root layout and never
// unmounts on client-side navigation -- otherwise its canvas would tear down and rebuild its
// random grid, restarting the scroll animation, every time a route that wants it navigates to
// another route that wants it (lobby -> tables -> table pregame). Pages that want it visible
// toggle this shared flag on mount instead of rendering their own `<TileMuralBackground>`, so the
// canvas itself is untouched -- only its opacity changes.
class MuralVisibility {
	visible = $state(false);
}

export const muralVisibility = new MuralVisibility();

// call once from a page's `<script>` (component initialization, not inside a callback) to claim
// mural visibility for as long as that page stays mounted, releasing it again on unmount. `wanted`
// is a getter rather than a plain boolean so the claim can vary reactively while mounted --
// `/table/[id]` wants the mural only during its pregame states, not once the game itself starts.
export function claimMuralVisible(wanted: () => boolean = () => true): void {
	$effect(() => {
		muralVisibility.visible = wanted();
		return () => {
			muralVisibility.visible = false;
		};
	});
}
