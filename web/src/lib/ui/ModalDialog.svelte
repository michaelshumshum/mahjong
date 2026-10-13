<script module lang="ts">
	const openDialogs: HTMLDialogElement[] = [];

	// fired whenever a modal opens or closes.
	export const TOP_LAYER_EVENT = 'mahjong:top-layer-change';

	export function topmostDialog(): HTMLDialogElement | null {
		return openDialogs.at(-1) ?? null;
	}

	// attachment: keeps `el` in the topmost open modal (else its parent), outside it is inert.
	// `el` must be its parent's only child: svelte unmounts by walking sibling ranges.
	export function followTopmostDialog(el: HTMLElement): () => void {
		const home = el.parentElement;
		if (!home) return () => {};
		const place = () => {
			const target = topmostDialog() ?? home;
			if (el.parentElement !== target) target.append(el);
		};
		place();
		window.addEventListener(TOP_LAYER_EVENT, place);
		return () => {
			window.removeEventListener(TOP_LAYER_EVENT, place);
			el.remove();
		};
	}
</script>

<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		onCancel,
		label,
		labelledby,
		describedby,
		role,
		testid,
		placement = 'center',
		children
	}: {
		// Escape / close request; omitted = not dismissable, the request is swallowed.
		onCancel?: () => void;
		label?: string;
		labelledby?: string;
		describedby?: string;
		role?: 'alertdialog';
		testid?: string;
		placement?: 'center' | 'sheet' | 'scroll';
		children: Snippet;
	} = $props();

	let dialogEl: HTMLDialogElement | undefined = $state();
	let closingOnDestroy = false;

	$effect(() => {
		const el = dialogEl;
		if (!el) return;
		const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
		if (!el.open) el.showModal();
		openDialogs.push(el);
		el.querySelector<HTMLElement>('[data-autofocus]')?.focus();
		window.dispatchEvent(new Event(TOP_LAYER_EVENT));
		return () => {
			closingOnDestroy = true;
			openDialogs.splice(openDialogs.indexOf(el), 1);
			if (el.open) el.close();
			window.dispatchEvent(new Event(TOP_LAYER_EVENT));
			if (opener?.isConnected) opener.focus();
		};
	});

	function handleCancel(event: Event): void {
		event.preventDefault();
		onCancel?.();
	}

	// chrome force-closes a dialog whose cancel was already prevented without user activation in
	// between; the owner still renders it, so treat it as a cancel or reopen.
	function handleClose(): void {
		if (closingOnDestroy || !dialogEl) return;
		if (onCancel) onCancel();
		else dialogEl.showModal();
	}
</script>

<dialog
	bind:this={dialogEl}
	class="modal modal--{placement}"
	{role}
	aria-label={label}
	aria-labelledby={labelledby}
	aria-describedby={describedby}
	data-testid={testid}
	oncancel={handleCancel}
	onclose={handleClose}
>
	{@render children()}
</dialog>

<style lang="scss">
	@use '$lib/styles/layout';

	// the dialog box itself is the scrim, so every panel keeps centering exactly as the old
	// fixed-position overlay divs did.
	.modal {
		position: fixed;
		inset: 0;
		width: 100%;
		height: 100%;
		max-width: none;
		max-height: none;
		margin: 0;
		padding: var(--space-3);
		border: 0;
		background: rgb(0 0 0 / 0.5);
		color: var(--color-text);
		overflow-y: auto;

		&[open] {
			display: flex;
			align-items: center;
			justify-content: center;
		}

		&:focus-visible {
			outline: none;
		}

		&::backdrop {
			background: transparent;
		}
	}

	.modal--sheet {
		background: rgb(0 0 0 / 0.62);

		@include layout.phone-only {
			padding: 0;

			&[open] {
				align-items: flex-end;
			}
		}
	}

	// phone landscape: lighter, so your hand stays readable under a sheet that leaves it visible.
	.modal--sheet {
		@include layout.phone-landscape {
			background: rgb(0 0 0 / 0.35);
		}
	}

	.modal--scroll {
		background: rgb(0 0 0 / 0.7);

		&[open] {
			align-items: flex-start;
		}
	}
</style>
