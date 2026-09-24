// The mural background mounts once in the root layout and never unmounts on navigation, so its
// canvas doesn't tear down and restart every time between two mural routes. Pages toggle this
// shared flag on mount instead of rendering their own instance.
class MuralVisibility {
	visible = $state(false);
}

export const muralVisibility = new MuralVisibility();

// call once from a page's <script> to claim mural visibility while mounted, releasing on
// unmount. `wanted` is a getter, not a boolean, so the claim can vary reactively while mounted.
export function claimMuralVisible(wanted: () => boolean = () => true): void {
	$effect(() => {
		muralVisibility.visible = wanted();
		return () => {
			muralVisibility.visible = false;
		};
	});
}
