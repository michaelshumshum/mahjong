<script lang="ts">
	import DialogTimer from '$lib/ui/DialogTimer.svelte';
	import CloseButton from '$lib/ui/CloseButton.svelte';
	import FaanBreakdown from '$lib/ui/FaanBreakdown.svelte';
	import type { MockHandResult, MockMeld } from '$lib/table/mock-game-state';
	import { m } from '$lib/paraglide/messages.js';

	let {
		handResult,
		handNo,
		handEndHoldMs,
		seatNames,
		winnerMelds,
		onDismiss
	}: {
		handResult: MockHandResult;
		handNo: number;
		handEndHoldMs: number | null;
		seatNames: Record<0 | 1 | 2 | 3, string>;
		winnerMelds: MockMeld[];
		onDismiss: () => void;
	} = $props();
</script>

<div class="faan-overlay" data-testid="faan-overlay">
	{#key handNo}
		<div class="hand-end-timer">
			<DialogTimer durationMs={handEndHoldMs ?? 0} size={40} onClose={onDismiss} />
		</div>
	{/key}
	<div class="panel">
		<CloseButton onclick={onDismiss} />
		{#if handResult.outcome === 'win'}
			<FaanBreakdown
				winner={handResult.winner as 0 | 1 | 2 | 3}
				{seatNames}
				winningHand={handResult.winningHand ?? []}
				melds={winnerMelds}
				patterns={handResult.patterns ?? []}
				totalFaan={handResult.totalFaan ?? 0}
				payments={handResult.payments ?? {}}
			/>
		{:else}
			<section
				class="hand-end-summary"
				data-testid="hand-end-draw"
				aria-label={m.handEndOverlay_resultAriaLabel()}
			>
				<h2>{m.handEndOverlay_handHeading({ handNo })}</h2>
				<p>{m.handEndOverlay_drawLabel()}</p>
			</section>
		{/if}
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	// centered, scrim-backed -- a hand result gets full modal weight, not a translucent row.
	.faan-overlay {
		@include buttons.modal-scrim;
		flex-direction: column;
		gap: var(--space-3);
	}

	.hand-end-summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		// wide enough that a short heading (e.g. "Hand 6") never sits under the CloseButton in
		// the panel's top-right corner
		min-width: 14rem;
		max-width: 24rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}

		p {
			margin: 0;
			color: var(--color-text-muted);
		}
	}

	// hugs whatever content it wraps so CloseButton sits against the panel's own corner.
	.panel {
		position: relative;
	}
</style>
