<script lang="ts">
	let { onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void } = $props();
</script>

<div class="panel-overlay">
	<div
		class="confirm-dialog"
		role="alertdialog"
		aria-label="Leave game"
		aria-describedby="leave-confirm-desc"
	>
		<h2>Leave this table?</h2>
		<p id="leave-confirm-desc">Your seat switches to autoplay until you reconnect.</p>
		<div class="confirm-actions">
			<button type="button" onclick={onCancel}>Cancel</button>
			<button type="button" class="confirm-leave" onclick={onConfirm}>Leave game</button>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

	.confirm-dialog {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: 100%;
		max-width: 22rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		text-align: center;
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

	.confirm-actions {
		display: flex;
		justify-content: center;
		gap: var(--space-3);

		button {
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-4);
			font: inherit;
			cursor: pointer;
			@include buttons.btn-secondary;
		}

		.confirm-leave {
			@include buttons.btn-primary;
		}
	}
</style>
