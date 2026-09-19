<script lang="ts">
	import type { TileCode } from '../table/tile-code';
	import { claimOptionKey, claimOptionLabel } from './claim-option';

	export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

	// mirrors the wire `claim{window_id, choice, tiles?}` shape (docs/02-protocol.md §2):
	// `tiles` only disambiguates `chow` (two options can claim the same discard into
	// different runs, e.g. 4s-5s vs 5s-7s completing a discarded 6s) — no other kind is ever
	// ambiguous once the server has offered it. No `window_id` here: this component is pure
	// presentation, wiring a real offer to a real window is the caller's job (`+page.svelte`'s
	// `chooseClaim`).
	export interface ClaimOption {
		kind: ClaimKind;
		tiles?: TileCode[];
	}

	let { options, onChoose }: { options: ClaimOption[]; onChoose: (option: ClaimOption) => void } =
		$props();
</script>

<div class="claim-buttons" role="group" aria-label="Claim options">
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

	// bottom-center per docs/03-frontend.md §5; fixed rather than relying on a positioned
	// ancestor, since this component isn't slotted into the real table overlay stack yet.
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
		min-width: 44px;
		min-height: 44px;
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

	// Win: the one urgent action a claim window can offer — stamped-seal primary tier. Same
	// box geometry as the other tiers (the TimerRing sits fixed just above this row with only
	// var(--space-2) of clearance — a taller Win button visibly collides with it), so the
	// hierarchy comes from weight/shadow/colour alone, not size.
	.claim-btn--win {
		@include buttons.btn-primary;
	}

	.claim-btn:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
