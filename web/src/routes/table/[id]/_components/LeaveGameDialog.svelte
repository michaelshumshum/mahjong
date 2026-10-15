<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import ModalDialog from '$lib/ui/ModalDialog.svelte';

	let { onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void } = $props();
</script>

<ModalDialog
	role="alertdialog"
	label={m.leaveGameDialog_ariaLabel()}
	describedby="leave-confirm-desc"
	{onCancel}
>
	<div class="confirm-dialog">
		<h2>{m.leaveGameDialog_title()}</h2>
		<p id="leave-confirm-desc">{m.leaveGameDialog_description()}</p>
		<div class="confirm-actions">
			<button type="button" data-autofocus onclick={onCancel}
				>{m.leaveGameDialog_cancelButton()}</button
			>
			<button type="button" class="confirm-leave" onclick={onConfirm}
				>{m.leaveGameDialog_confirmButton()}</button
			>
		</div>
	</div>
</ModalDialog>

<style lang="scss">
	@use '$lib/styles/buttons';

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
			@include buttons.btn-base(var(--space-4));
			@include buttons.btn-secondary;
		}

		.confirm-leave {
			@include buttons.btn-primary;
		}
	}
</style>
