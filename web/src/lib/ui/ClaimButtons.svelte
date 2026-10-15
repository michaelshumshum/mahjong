<script lang="ts">
	import type { ClaimOption } from '$lib/game/types';
	import { claimOptionAriaLabel, claimOptionKey, claimOptionLabel } from './claim-option';
	import TileOptionLabel from './TileOptionLabel.svelte';
	import { m } from '$lib/paraglide/messages.js';

	let { options, onChoose }: { options: ClaimOption[]; onChoose: (option: ClaimOption) => void } =
		$props();
</script>

<div class="claim-buttons" role="group" aria-label={m.claimButtons_ariaLabel()}>
	{#each options as option, index (claimOptionKey(option, index))}
		<button
			type="button"
			class="claim-btn claim-btn--{option.kind}"
			aria-label={claimOptionAriaLabel(option)}
			onclick={() => onChoose(option)}
		>
			<TileOptionLabel label={claimOptionLabel(option)} tiles={option.tiles} />
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
		@include buttons.btn-base(var(--space-4));
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
