import { describe, it, expect } from 'vitest';
import { flushSync } from 'svelte';
import { muralVisibility, claimMuralVisible } from './mural-visibility.svelte';

// Must run under the 'client' (browser-mode) vitest project -- $effect/$effect.root no-op under
// the 'server' project's SSR compile target (web/AGENTS.md's *.svelte.spec.ts note).
describe('muralVisibility', () => {
	it('is visible while a claim is active, hidden once released', () => {
		const dispose = $effect.root(() => {
			claimMuralVisible();
		});
		flushSync();
		expect(muralVisibility.visible).toBe(true);

		dispose();
		flushSync();
		expect(muralVisibility.visible).toBe(false);
	});

	it('stays visible while any claim is still active', () => {
		const disposeA = $effect.root(() => claimMuralVisible());
		const disposeB = $effect.root(() => claimMuralVisible());
		flushSync();
		expect(muralVisibility.visible).toBe(true);

		disposeA();
		flushSync();
		expect(muralVisibility.visible).toBe(true); // B still holds it

		disposeB();
		flushSync();
		expect(muralVisibility.visible).toBe(false);
	});

	it('follows a reactive `wanted` getter without needing to unmount', () => {
		let wanted = $state(false);
		const dispose = $effect.root(() => claimMuralVisible(() => wanted));
		flushSync();
		expect(muralVisibility.visible).toBe(false);

		wanted = true;
		flushSync();
		expect(muralVisibility.visible).toBe(true);

		wanted = false;
		flushSync();
		expect(muralVisibility.visible).toBe(false);

		dispose();
	});

	// Regression: gate-release and page-claim land in the same reactive flush; a last-write-wins
	// boolean left `visible` stuck false depending on effect order. Ref-counting fixes that.
	it('stays visible when one claim releases as another claims in the same flush', () => {
		let gateWanted = $state(true);
		const disposeGate = $effect.root(() => claimMuralVisible(() => gateWanted));
		flushSync();
		expect(muralVisibility.visible).toBe(true);

		// simulate the gate dismissing and the underlying page mounting its own claim together,
		// before either has had a chance to flush.
		gateWanted = false;
		const disposePage = $effect.root(() => claimMuralVisible());
		flushSync();

		expect(muralVisibility.visible).toBe(true);

		disposeGate();
		disposePage();
	});
});
