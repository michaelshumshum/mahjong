import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mount, unmount } from 'svelte';
import TableCard from '../../routes/tables/_components/TableCard.svelte';
import type { TableSummary } from '$lib/net/lobby';

// dynamic import inside the factory itself -- see lobby/page.svelte.spec.ts's comment on why.
vi.mock('$lib/paraglide/messages.js', async () => {
	const { createMessagesProxy } = await import('../../test/mocks');
	return { m: createMessagesProxy() };
});
// TableCard pulls in $lib/net/lobby (seatedCount's import) for apiBaseUrl(), which reads
// $env/dynamic/public -- unset outside SvelteKit's own dev/build server (web/AGENTS.md).
vi.mock('$env/dynamic/public', () => ({ env: {} }));

describe('TableCard', () => {
	let target: HTMLDivElement;
	let component: ReturnType<typeof mount>;
	const onOpen = vi.fn();

	const openTable: TableSummary = {
		id: 'ABCD',
		status: 'open',
		hand_no: 1,
		seats: [
			{ status: 'connected', name: 'Alice' },
			{ status: 'empty', name: null },
			{ status: 'empty', name: null },
			{ status: 'empty', name: null }
		]
	};

	const inProgressTable: TableSummary = {
		id: 'EFGH',
		status: 'in_progress',
		hand_no: 3,
		seats: [
			{ status: 'connected', name: 'Bob' },
			{ status: 'connected', name: 'Carol' },
			{ status: 'connected', name: 'Dave' },
			{ status: 'bot', name: null }
		]
	};

	beforeEach(() => {
		target = document.createElement('div');
		document.body.appendChild(target);
		onOpen.mockClear();
	});

	afterEach(() => {
		unmount(component);
		target.remove();
	});

	it('displays the table code and seat list', () => {
		component = mount(TableCard, { target, props: { table: openTable, hasJoined: false, onOpen } });
		expect(target.textContent).toContain('ABCD');
		expect(target.textContent).toContain('Alice');
		expect(target.querySelector('[data-testid="table-card-action"]')?.textContent).toContain(
			'tableCard_sitDownButton'
		);
	});

	it('shows a rejoin button when the user has already joined', () => {
		component = mount(TableCard, { target, props: { table: openTable, hasJoined: true, onOpen } });
		expect(target.querySelector('[data-testid="table-card-action"]')?.textContent).toContain(
			'tableCard_rejoinButton'
		);
	});

	it('shows a watch button for in-progress tables', () => {
		component = mount(TableCard, {
			target,
			props: { table: inProgressTable, hasJoined: false, onOpen }
		});
		expect(target.querySelector('[data-testid="table-card-action"]')?.textContent).toContain(
			'tableCard_watchButton'
		);
	});

	it('calls onOpen with the table id when the action button is clicked', () => {
		component = mount(TableCard, { target, props: { table: openTable, hasJoined: false, onOpen } });
		const action = target.querySelector('[data-testid="table-card-action"]') as HTMLButtonElement;
		action.click();
		expect(onOpen).toHaveBeenCalledWith('ABCD');
	});
});
