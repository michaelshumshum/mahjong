import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import TablesPage from '../../routes/tables/+page.svelte';
import { goto } from '$app/navigation';
import { fetchTables } from '$lib/net/lobby';
import type { TableSummary } from '$lib/net/lobby';

const tables: TableSummary[] = [
	{
		id: 'ABCD',
		status: 'open',
		hand_no: 1,
		seats: [
			{ status: 'connected', name: 'Alice' },
			{ status: 'empty', name: null },
			{ status: 'empty', name: null },
			{ status: 'empty', name: null }
		]
	},
	{
		id: 'EFGH',
		status: 'in_progress',
		hand_no: 3,
		seats: [
			{ status: 'connected', name: 'Bob' },
			{ status: 'connected', name: 'Carol' },
			{ status: 'connected', name: 'Dave' },
			{ status: 'bot', name: null }
		]
	}
];
// dynamic import inside the factory itself -- see lobby/page.svelte.spec.ts's comment on why.
vi.mock('$lib/paraglide/messages.js', async () => {
	const { createMessagesProxy } = await import('../../test/mocks');
	return { m: createMessagesProxy() };
});
vi.mock('$app/navigation', () => ({ goto: vi.fn() }));
vi.mock('$lib/net/lobby', () => ({
	fetchTables: vi.fn(),
	createTable: vi.fn(),
	seatedCount: (table: TableSummary) => table.seats.filter((s) => s.status !== 'empty').length
}));
vi.mock('$lib/ui/settings-storage', () => ({
	hasJoinedTable: vi.fn(() => false),
	loadCreateTableSetup: vi.fn(() => null),
	saveCreateTableSetup: vi.fn()
}));

describe('TablesPage', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount>;

	beforeEach(() => {
		target = document.createElement('div');
		document.body.appendChild(target);
		vi.mocked(goto).mockClear();
		vi.mocked(fetchTables).mockClear();
		vi.mocked(fetchTables).mockResolvedValue(tables);
	});

	afterEach(() => {
		unmount(component);
		target.remove();
	});

	it('renders the join-by-code panel', () => {
		component = mount(TablesPage, { target });
		expect(target.querySelector('[data-testid="join-by-code-input"]')).not.toBeNull();
		expect(target.querySelector('[data-testid="join-by-code-submit"]')).not.toBeNull();
	});

	it('loads and renders table cards', async () => {
		component = mount(TablesPage, { target });
		await Promise.resolve();
		await Promise.resolve();
		const cards = target.querySelectorAll('[data-testid="table-card"]');
		expect(cards.length).toBe(2);
		expect(target.textContent).toContain('ABCD');
		expect(target.textContent).toContain('EFGH');
	});

	it('navigates to a table when join-by-code is submitted', async () => {
		component = mount(TablesPage, { target });
		const input = target.querySelector('[data-testid="join-by-code-input"]') as HTMLInputElement;
		const submit = target.querySelector('[data-testid="join-by-code-submit"]') as HTMLButtonElement;
		input.value = 'wxyz';
		input.dispatchEvent(new Event('input'));
		await Promise.resolve();
		submit.click();
		expect(goto).toHaveBeenCalledWith('/table/WXYZ');
	});
});
