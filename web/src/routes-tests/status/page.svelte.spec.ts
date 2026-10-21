import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import StatusPage from '../../routes/status/+page.svelte';
import { fetchServerStatus, type StatusResponse } from '$lib/net/server-status';

// dynamic import inside the factory itself -- see lobby/page.svelte.spec.ts's comment on why.
vi.mock('$lib/paraglide/messages.js', async () => {
	const { createMessagesProxy } = await import('../../test/mocks');
	return { m: createMessagesProxy() };
});
vi.mock('$lib/net/server-status', () => ({ fetchServerStatus: vi.fn() }));

const body: StatusResponse = {
	status: 'ok',
	uptime_seconds: 3_700,
	players_online: 7,
	spectators: 2,
	tables_playing: 2,
	tables_waiting: 1,
	capacity_pct: 1,
	games_finished_24h: null,
	bot_decision_ms: { p50_ms: 1.2, p95_ms: 4.6 },
	loop_lag_ms: 0.4,
	history: [
		{ ts: 1_000, players: 3, tables: 1, bot_p95_ms: 4, loop_lag_ms: 0.2 },
		{ ts: 2_000, players: 7, tables: 2, bot_p95_ms: null, loop_lag_ms: 0.4 }
	]
};

async function settle(): Promise<void> {
	for (let i = 0; i < 4; i++) await Promise.resolve();
}

describe('StatusPage', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount>;

	beforeEach(() => {
		target = document.createElement('div');
		document.body.appendChild(target);
		vi.mocked(fetchServerStatus).mockReset();
	});

	afterEach(() => {
		unmount(component);
		target.remove();
	});

	it('shows the server state, stat tiles and history charts', async () => {
		vi.mocked(fetchServerStatus).mockResolvedValue(body);
		component = mount(StatusPage, { target });
		await settle();
		const banner = target.querySelector('[data-testid="status-banner"]');
		expect(banner?.getAttribute('data-status')).toBe('ok');
		const players = target.querySelector('[data-testid="status-tile-players"] .value');
		expect(players?.textContent).toBe('7');
		const games = target.querySelector('[data-testid="status-tile-games"] .value');
		expect(games?.textContent).toBe('statusPage_notAvailable');
		expect(target.querySelector('[data-testid="status-chart-players"] path.line')).not.toBeNull();
		// one non-null bot point: not enough to draw a line
		expect(target.querySelector('[data-testid="status-chart-bots"] svg')).toBeNull();
	});

	it('reports an unreachable server instead of waiting on it', async () => {
		vi.mocked(fetchServerStatus).mockRejectedValue(new Error('offline'));
		component = mount(StatusPage, { target });
		await settle();
		const banner = target.querySelector('[data-testid="status-banner"]');
		expect(banner?.getAttribute('data-status')).toBe('unreachable');
		expect(target.querySelector('[data-testid="status-tile-players"]')).toBeNull();
	});
});
