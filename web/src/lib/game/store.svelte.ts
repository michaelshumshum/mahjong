import { flushSync } from 'svelte';
import { reduce } from '../net/reducer';
import { initialClientGameState, type ClientGameState, type ConnectionStatus } from './state';
import type { MahjongSocket } from '../net/socket';
import type { ServerEvent } from '../net/protocol';

/**
 * Client game state store (docs/03-frontend.md §6). One-way flow only: server event ->
 * lib/net/reducer.ts's `reduce` -> `this.state` -> components read it (web/AGENTS.md). The
 * store never mutates game truth optimistically — its only mutator is `#apply`, driven
 * exclusively by events the socket actually received; construct a `MahjongSocket`, hand it to
 * this store, and every subsequent state change traces back to a real server frame.
 *
 * Doesn't wire itself to `/table/[id]`'s rendering (a later sub-task) — this is the plumbing
 * layer the doc's own `lib/game/` line describes: "client state store (`$state`)".
 */
export class GameStore {
	/** Current redacted game state, rebuilt incrementally from the real event stream. */
	state = $state<ClientGameState>(initialClientGameState());
	/** Mirrors the socket's own connection/resync status (lib/net/socket.ts). */
	connection = $state<ConnectionStatus>('idle');
	/** Last seq applied to `state` — bookkeeping for UI/debugging, distinct from the socket's
	 * own internal gap-detection counter (lib/net/socket.ts owns the correctness-critical copy). */
	seq = $state<number | null>(null);
	/** Bumped on every apply(); cheap change signal for non-reactive consumers holding a
	 * `$state.snapshot(store.state)` (web/AGENTS.md: `$state` fields are deep proxies). */
	version = $state(0);

	#socket: MahjongSocket;
	#dispose: () => void;

	constructor(socket: MahjongSocket) {
		this.#socket = socket;
		// Effects need an owner outside a .svelte file (web/AGENTS.md) — this is the one place
		// lib/game subscribes to a live external source (the socket) and pushes into $state.
		// Neither effect reads reactive state, so each runs exactly once and only exists to pair
		// a subscription with its teardown under an explicit disposer.
		this.#dispose = $effect.root(() => {
			$effect(() => {
				const off = socket.onEvent((event) => this.#apply(event));
				return off;
			});
			$effect(() => {
				const off = socket.onStatus((status) => {
					this.connection = status;
				});
				return off;
			});
		});
		// Effects created inside $effect.root are otherwise scheduled onto the next microtask
		// flush (a browser-tab paint, or the normal component-effect cycle). This store is
		// constructed outside any component, so nothing else guarantees that flush happens
		// before a caller can observe it — flush now so both subscriptions are live, and the
		// socket already carries setSeat(...) calls from anything already buffered, the instant
		// the constructor returns.
		flushSync();
	}

	/** The socket this store is wired to — intents (`join`/`discard`/`claim`/...) go through it
	 * directly; the store itself only ever reads events, never sends. */
	get socket(): MahjongSocket {
		return this.#socket;
	}

	/** This connection's own seat, once known (learned from `state_sync.seat`), else `null`. */
	get seat(): number | null {
		return this.state.seat;
	}

	/** The currently open claim window offered to this seat, if any. */
	get claimOffer(): ClientGameState['claimOffer'] {
		return this.state.claimOffer;
	}

	#apply(event: ServerEvent): void {
		if (typeof event.seq === 'number') this.seq = event.seq;
		this.state = reduce(this.state, event);
		if (event.t === 'state_sync') this.#socket.setSeat(event.d.seat);
		this.version++;
	}

	/** Tears down the socket subscriptions this store owns. Call when the store itself goes out
	 * of scope (e.g. leaving `/table/[id]`) — effects need an explicit disposer, there's no
	 * component lifecycle here to do it automatically. */
	destroy(): void {
		this.#dispose();
	}
}
