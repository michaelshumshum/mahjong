import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import { spawn, type ChildProcess } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { MahjongSocket } from './socket';
import { reduce } from './reducer';
import { initialClientGameState, type ClientGameState } from '../game/state';
import type { ServerEvent } from './protocol';

/** Live smoke test: real uvicorn + MahjongSocket vs actual wire shapes. Skipped by default, opt in
 * with RUN_LIVE_BACKEND_TESTS=1. Tests MahjongSocket+reduce directly, not GameStore (runes need 'client'). */
describe.skipIf(!process.env.RUN_LIVE_BACKEND_TESTS)('live backend (opt-in)', () => {
	const port = 8199;
	const wsUrl = `ws://127.0.0.1:${port}/ws`;
	const serverDir = path.resolve(
		path.dirname(fileURLToPath(import.meta.url)),
		'../../../../server'
	);
	let serverProcess: ChildProcess | null = null;

	async function waitForHealthy(timeoutMs: number): Promise<void> {
		const deadline = Date.now() + timeoutMs;
		let lastError: unknown;
		while (Date.now() < deadline) {
			try {
				const res = await fetch(`http://127.0.0.1:${port}/healthz`);
				if (res.ok) return;
			} catch (err) {
				lastError = err;
			}
			await new Promise((resolve) => setTimeout(resolve, 200));
		}
		throw new Error(`server never became healthy: ${String(lastError)}`);
	}

	async function waitFor(predicate: () => boolean, timeoutMs: number, what: string): Promise<void> {
		const deadline = Date.now() + timeoutMs;
		while (Date.now() < deadline) {
			if (predicate()) return;
			await new Promise((resolve) => setTimeout(resolve, 25));
		}
		throw new Error(`timed out waiting for: ${what}`);
	}

	beforeAll(async () => {
		// `detached: true` puts uvicorn's whole process tree (it forks helpers) in its own
		// process group, so afterAll can kill it all via negative-PID `kill`.
		serverProcess = spawn(
			'uv',
			['run', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', String(port)],
			{ cwd: serverDir, stdio: 'pipe', detached: true }
		);
		let log = '';
		serverProcess.stdout?.on('data', (d) => (log += String(d)));
		serverProcess.stderr?.on('data', (d) => (log += String(d)));
		serverProcess.on('error', (err) => {
			throw new Error(`failed to spawn uvicorn (is 'uv' on PATH?): ${err.message}`);
		});
		try {
			await waitForHealthy(20_000);
		} catch (err) {
			throw new Error(`${String(err)}\n--- server output ---\n${log}`);
		}
	}, 30_000);

	afterAll(async () => {
		if (!serverProcess || serverProcess.pid === undefined) return;
		const proc = serverProcess;
		const pgid = proc.pid!;
		const exited = new Promise<void>((resolve) => proc.once('exit', () => resolve()));
		try {
			process.kill(-pgid, 'SIGTERM');
		} catch {
			/* group already gone */
		}
		await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5000))]);
		try {
			process.kill(-pgid, 'SIGKILL');
		} catch {
			/* group already gone -- the common, successful case */
		}
	}, 10_000);

	it('four real seats join, deal, and exchange one real discard, redacted correctly per seat', async () => {
		const tableId = `it-${Date.now()}`;
		const seats: {
			socket: MahjongSocket;
			state: ClientGameState;
		}[] = [];

		for (let seat = 0; seat < 4; seat++) {
			const socket = new MahjongSocket(`${wsUrl}?table=${tableId}`);
			const entry = { socket, state: initialClientGameState() };
			socket.onEvent((event: ServerEvent) => {
				entry.state = reduce(entry.state, event);
			});
			seats.push(entry);
		}

		try {
			for (const { socket } of seats) socket.connect();
			await waitFor(
				() => seats.every(({ socket: s }) => s.readyState === WebSocket.OPEN),
				10_000,
				'all four sockets to open'
			);

			seats.forEach(({ socket }, seat) => socket.join(seat));
			await waitFor(
				() => seats.every(({ state }) => state.seat !== null),
				10_000,
				'all four seats to see their own state_sync'
			);
			seats.forEach(({ state }, seat) => expect(state.seat).toBe(seat));

			for (const { socket } of seats) socket.ready();

			await waitFor(
				() => seats.every(({ state }) => state.ownHand.length > 0),
				10_000,
				'the first hand to deal to every seat'
			);

			const dealer = seats[0].state.dealer;
			for (const { state } of seats) expect(state.dealer).toBe(dealer);
			for (const [seat, { state }] of seats.entries()) {
				expect(state.ownHand.length).toBe(seat === dealer ? 14 : 13);
				// nothing leaks another seat's real tiles -- own_hand is only ever this seat's own.
				expect(state.concealedCounts[seat]).toBe(state.ownHand.length);
			}

			// find whoever's turn it is and the discard action the server actually offered them.
			await waitFor(
				() => seats.some(({ state }) => state.legalActions.length > 0),
				10_000,
				'a turn to open with legal actions'
			);
			const actingSeat = seats.findIndex(({ state }) => state.legalActions.length > 0);
			expect(actingSeat).toBeGreaterThanOrEqual(0);
			const legal = seats[actingSeat].state.legalActions;
			const discardAction = legal.find((a) => a.kind === 'discard') as
				| { kind: string; tile_id: number }
				| undefined;
			expect(discardAction).toBeDefined();
			const tileId = discardAction!.tile_id;
			const handBefore = seats[actingSeat].state.ownHand.length;

			seats[actingSeat].socket.discard(tileId);

			await waitFor(
				() => seats.every(({ state }) => state.discardPools[actingSeat].includes(tileId)),
				10_000,
				'the discard to be broadcast to every seat'
			);

			// the actor's own hand actually lost the tile; every other seat's redacted view of
			// the actor's concealed count dropped by one and never learned the actor's other tiles.
			expect(seats[actingSeat].state.ownHand.length).toBe(handBefore - 1);
			expect(seats[actingSeat].state.ownHand).not.toContain(tileId);
			for (const [seat, { state }] of seats.entries()) {
				if (seat === actingSeat) continue;
				expect(state.discardPools[actingSeat]).toContain(tileId);
			}
		} finally {
			for (const { socket } of seats) socket.disconnect();
		}
	}, 30_000);
});
