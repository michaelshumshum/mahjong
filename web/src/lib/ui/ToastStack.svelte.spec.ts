import { afterEach, describe, expect, it } from 'vitest';
import { createRawSnippet, flushSync } from 'svelte';
import { cleanup, cleanupAll, render } from '$lib/table/test-render';
import ModalDialog from './ModalDialog.svelte';
import ToastStack from './ToastStack.svelte';

const children = createRawSnippet(() => ({
	render: () => '<div style="width: 100vw; height: 100vh">modal content</div>'
}));

describe('ToastStack with a modal dialog', () => {
	afterEach(cleanupAll);

	it('moves into an open modal, staying the topmost hit target, and back home on close', () => {
		const queue = [
			{ id: 1, message: 'still visible', durationMs: 60000, severity: 'info' as const }
		];
		const { target } = render(ToastStack, { queue, onDismiss: () => {} });
		flushSync();
		const modal = render(ModalDialog, { children });
		flushSync();

		const stack = document.querySelector<HTMLElement>('.toast-stack')!;
		expect(stack.parentElement).toBe(document.querySelector('dialog'));
		const box = stack.querySelector('.toast')!.getBoundingClientRect();
		const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2);
		expect(stack.contains(hit)).toBe(true);

		cleanup(modal);
		expect(target.contains(stack)).toBe(true);
	});
});
