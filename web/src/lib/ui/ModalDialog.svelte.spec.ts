import { afterEach, describe, expect, it, vi } from 'vitest';
import { createRawSnippet, flushSync } from 'svelte';
import { cleanup, cleanupAll, render } from '$lib/table/test-render';
import ModalDialog, { TOP_LAYER_EVENT } from './ModalDialog.svelte';

const children = createRawSnippet(() => ({
	render: () =>
		'<div><button type="button">first</button><button data-autofocus>second</button></div>'
}));

function escape(target: Element): void {
	target.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
}

describe('ModalDialog', () => {
	afterEach(cleanupAll);

	it('opens as a modal in the top layer and focuses [data-autofocus]', () => {
		const { target } = render(ModalDialog, { children, label: 'Test' });
		flushSync();
		const dialog = target.querySelector('dialog')!;
		expect(dialog.open).toBe(true);
		expect(dialog.matches(':modal')).toBe(true);
		expect(dialog.getAttribute('aria-label')).toBe('Test');
		expect(document.activeElement?.textContent).toBe('second');
	});

	it('routes a cancel (Escape close request) to onCancel and stays open until unmounted', () => {
		const onCancel = vi.fn();
		const { target } = render(ModalDialog, { children, onCancel });
		flushSync();
		const dialog = target.querySelector('dialog')!;
		const cancel = new Event('cancel', { cancelable: true });
		dialog.dispatchEvent(cancel);
		expect(onCancel).toHaveBeenCalledOnce();
		expect(cancel.defaultPrevented).toBe(true);
		expect(dialog.open).toBe(true);
	});

	it('reopens instead of closing when it has no onCancel', async () => {
		const { target } = render(ModalDialog, { children });
		flushSync();
		const dialog = target.querySelector('dialog')!;
		// the close event is queued as a task; this listener runs after the component's own.
		const closed = new Promise((resolve) =>
			dialog.addEventListener('close', resolve, { once: true })
		);
		dialog.close();
		await closed;
		expect(dialog.open).toBe(true);
	});

	it('returns focus to the opener on unmount', () => {
		const opener = document.createElement('button');
		document.body.appendChild(opener);
		opener.focus();
		const result = render(ModalDialog, { children });
		flushSync();
		expect(document.activeElement).not.toBe(opener);
		cleanup(result);
		expect(document.activeElement).toBe(opener);
		opener.remove();
	});

	it('announces its opening so the toast popover can re-raise above it', () => {
		const listener = vi.fn();
		window.addEventListener(TOP_LAYER_EVENT, listener);
		render(ModalDialog, { children });
		flushSync();
		window.removeEventListener(TOP_LAYER_EVENT, listener);
		expect(listener).toHaveBeenCalled();
	});

	it('swallows Escape keydown without a native close when not dismissable', () => {
		const { target } = render(ModalDialog, { children });
		flushSync();
		escape(target.querySelector('button')!);
		expect(target.querySelector('dialog')!.open).toBe(true);
	});
});
