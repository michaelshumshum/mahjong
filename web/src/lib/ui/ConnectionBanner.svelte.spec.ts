import { describe, it, expect, afterEach } from 'vitest';
import { render, cleanupAll } from '$lib/table/test-render';
import ConnectionBanner from './ConnectionBanner.svelte';

function wait(ms: number): Promise<void> {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

describe('ConnectionBanner', () => {
	afterEach(cleanupAll);

	it('stays hidden while the connection is open', async () => {
		const { target } = render(ConnectionBanner, { connection: 'open', revealDelayMs: 0 });
		await wait(10);
		expect(target.querySelector('[data-testid="connection-banner"]')).toBeNull();
	});

	it('stays hidden for a brief closed/resyncing blip (before revealDelayMs elapses)', () => {
		const { target } = render(ConnectionBanner, { connection: 'closed', revealDelayMs: 5000 });
		expect(target.querySelector('[data-testid="connection-banner"]')).toBeNull();
	});

	it('shows once closed outlasts revealDelayMs', async () => {
		const { target } = render(ConnectionBanner, { connection: 'closed', revealDelayMs: 10 });
		await wait(30);
		expect(target.querySelector('[data-testid="connection-banner"]')).not.toBeNull();
	});

	it('shows for a sustained resyncing connection too', async () => {
		const { target } = render(ConnectionBanner, { connection: 'resyncing', revealDelayMs: 10 });
		await wait(30);
		expect(target.querySelector('[data-testid="connection-banner"]')).not.toBeNull();
	});
});
