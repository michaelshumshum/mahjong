<script lang="ts">
	import ClaimButtons, { type ClaimOption } from '$lib/ui/ClaimButtons.svelte';
	import { m } from '$lib/paraglide/messages.js';

	// mock props only, no claim_offer wiring. Two chow options on the same discarded 6s
	// (4s-5s vs 5s-7s) exercises the multi-chow-option disambiguation.
	const demoClaimOptions: ClaimOption[] = [
		{ kind: 'chow', tiles: ['4s', '5s'] },
		{ kind: 'chow', tiles: ['5s', '7s'] },
		{ kind: 'pung' },
		{ kind: 'win' },
		{ kind: 'pass' }
	];
	let lastChoice = $state<ClaimOption | null>(null);
	function chooseDemo(option: ClaimOption): void {
		lastChoice = option;
	}
</script>

<h2>{m.claimButtonsDemo_heading()}</h2>
<p class="hint">
	{m.claimButtonsDemo_hint()}
</p>
{#if lastChoice}
	<p data-testid="claim-choice">
		chose: {lastChoice.kind}{lastChoice.tiles ? ` ${lastChoice.tiles.join('-')}` : ''}
	</p>
{/if}
<ClaimButtons options={demoClaimOptions} onChoose={chooseDemo} />

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
