<script lang="ts">
	import type { TileCode } from '../table/tile-code';
	import { claimOptionKey, claimOptionLabel } from './claim-option';
	import { m } from '$lib/paraglide/messages.js';

	export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

	// mirrors the wire claim{window_id, choice, tiles?} shape; `tiles` only disambiguates chow.
	// no `window_id` here -- pure presentation, wiring to a real window is the caller's job.
	export interface ClaimOption {
		kind: ClaimKind;
		tiles?: TileCode[];
	}

	let { options, onChoose }: { options: ClaimOption[]; onChoose: (option: ClaimOption) => void } =
		$props();
</script>

<div class="claim-buttons" role="group" aria-label={m.claimButtons_ariaLabel()}>
	{#each options as option, index (claimOptionKey(option, index))}
		<button
			type="button"
			class="claim-btn claim-btn--{option.kind}"
			onclick={() => onChoose(option)}
		>
			{claimOptionLabel(option)}
		</button>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	// fixed rather than relying on a positioned ancestor -- not slotted into the overlay stack yet.
	.claim-buttons {
		position: fixed;
		inset-inline: 0;
		bottom: var(--space-5);
		display: flex;
		justify-content: center;
		align-items: center;
		gap: var(--space-3);
		z-index: var(--z-overlay);
		pointer-events: none;
	}

	.claim-btn {
		pointer-events: auto;
		min-width: var(--tap-target-min);
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-4);
		font: inherit;
		cursor: pointer;
	}

	// Pung/Chow/Kong: standard claim actions, secondary tier.
	.claim-btn--chow,
	.claim-btn--pung,
	.claim-btn--kong {
		@include buttons.btn-secondary;
	}

	// Pass: the do-nothing option, tertiary/ghost so it never competes with a real claim.
	.claim-btn--pass {
		@include buttons.btn-ghost;
	}

	// same box geometry as the other tiers -- TimerRing sits fixed just above with only
	// var(--space-2) clearance, so a taller button would collide with it.
	.claim-btn--win {
		@include buttons.btn-primary;
	}
</style>
