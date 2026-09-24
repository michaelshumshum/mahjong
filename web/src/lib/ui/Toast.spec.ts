import { describe, it, expect } from 'vitest';
import { render } from 'svelte/server';
import Toast from './Toast.svelte';

// Auto-dismiss firing is covered in auto-close.spec.ts and end-to-end in routes/page.e2e.ts --
// this file only covers rendered markup.
describe('Toast', () => {
	const noop = () => {};

	it('renders the message', () => {
		const { body } = render(Toast, { props: { message: 'Reconnecting…', onDismiss: noop } });
		expect(body).toContain('Reconnecting…');
	});

	it('exposes the effective duration (default) for the auto-dismiss timer', () => {
		const { body } = render(Toast, { props: { message: 'x', onDismiss: noop } });
		expect(body).toContain('data-duration-ms="4000"');
	});

	it('exposes a custom duration when given', () => {
		const { body } = render(Toast, {
			props: { message: 'x', durationMs: 1500, onDismiss: noop }
		});
		expect(body).toContain('data-duration-ms="1500"');
	});

	it('renders a dismiss button', () => {
		const { body } = render(Toast, { props: { message: 'x', onDismiss: noop } });
		expect(body).toContain('aria-label="Dismiss"');
	});
});
