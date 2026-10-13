<script lang="ts">
	import DialogTimer from '$lib/ui/DialogTimer.svelte';
	import CloseButton from '$lib/ui/CloseButton.svelte';
	import ModalDialog from '$lib/ui/ModalDialog.svelte';
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

	let stamp = $derived(
		handResult.outcome !== 'win'
			? { kind: 'draw', label: m.handEndOverlay_stampDraw() }
			: handResult.winType === 'self_draw'
				? { kind: 'self-draw', label: m.handEndOverlay_stampSelfDraw() }
				: { kind: 'win', label: m.handEndOverlay_stampWin() }
	);
</script>

<!-- Escape dismisses, same as the close button: the hold is an acknowledgment, not a decision. -->
<ModalDialog
	testid="faan-overlay"
	label={m.handEndOverlay_resultAriaLabel()}
	placement="sheet"
	onCancel={onDismiss}
>
	<div class="hand-end-panel">
		<header class="hand-end-header">
			<span class="result-stamp result-stamp--{stamp.kind}" aria-hidden="true">{stamp.label}</span>
			<span class="hand-end-handno"
				>{handResult.outcome === 'win' ? m.handEndOverlay_handHeading({ handNo }) : ''}</span
			>
			<!-- no deadline known (a frozen mock, or a resync mid-hold): no ring and no auto-close,
				rather than a zero-length timer that would close the panel instantly. -->
			{#if handEndHoldMs !== null}
				{#key handNo}
					<span class="hand-end-timer">
						<DialogTimer durationMs={handEndHoldMs} size={32} onClose={onDismiss} />
					</span>
				{/key}
			{/if}
			<CloseButton onclick={onDismiss} />
		</header>
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
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.hand-end-panel {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: min(28rem, 100%);
		max-height: 100%;
		overflow-y: auto;
		padding: var(--space-4) var(--space-5) var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.phone-only {
			width: 100%;
			padding: var(--space-4);
			border-radius: var(--radius-lg) var(--radius-lg) 0 0;
			padding-bottom: calc(var(--space-4) + env(safe-area-inset-bottom));
		}

		// phone landscape: a wide centred card -- FaanBreakdown goes two-column to fit the height.
		@include layout.phone-landscape {
			align-self: center;
			width: min(52rem, 100%);
			gap: var(--space-2);
			padding: var(--space-2) var(--space-4) var(--space-3);
			border-radius: var(--radius-lg);
		}

		&:has(.hand-end-summary) {
			@include layout.phone-landscape {
				width: min(28rem, 100%);
			}
		}

		@include a11y.motion-ok {
			animation: panel-in var(--dur-3) var(--ease-out) both;
		}
	}

	@keyframes panel-in {
		from {
			opacity: 0;
			transform: translateY(16px) scale(0.98);
		}
	}

	// CloseButton is absolutely positioned in the panel's corner; the right padding keeps the
	// timer clear of it.
	.hand-end-header {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		min-height: var(--tap-target-min);
		padding-right: calc(var(--tap-target-min) + var(--space-1));
	}

	.hand-end-handno {
		flex: 1;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		letter-spacing: 0.04em;
	}

	.hand-end-timer {
		display: inline-flex;
	}

	// seal-ink stamp: double-ruled border, slightly off-square like a hand press.
	.result-stamp {
		display: inline-grid;
		place-items: center;
		padding: var(--space-1) var(--space-3);
		border: 3px double currentColor;
		border-radius: var(--radius-sm);
		color: var(--color-text);
		background: var(--color-accent);
		font-size: var(--font-size-lg);
		font-weight: 800;
		letter-spacing: 0.12em;
		line-height: 1.2;
		transform: rotate(-6deg);

		@include a11y.motion-ok {
			animation: stamp-in var(--dur-3) var(--ease-place) both;
		}
	}

	// the draw is a non-event: a muted ink stamp, never the urgent accent.
	.result-stamp--draw {
		color: var(--color-text-muted);
		background: var(--color-surface);
	}

	@keyframes stamp-in {
		from {
			opacity: 0;
			transform: rotate(-14deg) scale(1.8);
		}
		60% {
			opacity: 1;
		}
	}

	.hand-end-summary {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);

		h2 {
			margin: 0;
			font-size: var(--font-size-xl);
		}

		p {
			margin: 0;
			color: var(--color-text-muted);
		}
	}
</style>
