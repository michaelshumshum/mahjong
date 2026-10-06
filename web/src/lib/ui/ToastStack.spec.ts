import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import ToastStack from './ToastStack.svelte';

describe('ToastStack', () => {
	const noop = () => {};

	it('renders one Toast per queue entry', () => {
		const { body } = render(ToastStack, {
			props: {
				queue: [
					{ id: 1, message: 'first', durationMs: 4000, severity: 'info' },
					{ id: 2, message: 'second', durationMs: 4000, severity: 'error' }
				],
				onDismiss: noop
			}
		});
		expect(body).toContain('first');
		expect(body).toContain('second');
	});

	it('renders nothing for an empty queue', () => {
		const { body } = render(ToastStack, {
			props: { queue: [], onDismiss: noop }
		});
		expect(body).toContain('toast-stack');
		expect(body).not.toContain('class="toast"');
	});
});
