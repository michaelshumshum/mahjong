import { flushSync } from 'svelte';
import { reduce } from '../net/reducer';
import { initialClientGameState, type ClientGameState, type ConnectionStatus } from './state';
import type { MahjongSocket } from '../net/socket';
import type { ServerEvent } from '../net/protocol';

/** Client game state store (docs/03-frontend.md §6). `#apply` is the only mutator, driven
 * exclusively by events the socket receives. */
export class GameStore {
	state = $state<ClientGameState>(initialClientGameState());
	connection = $state<ConnectionStatus>('idle');
	/** UI/debug bookkeeping only — socket.ts owns the correctness-critical gap-detection copy. */
	seq = $state<number | null>(null);
	/** Bumped on every apply(); cheap change signal for non-reactive consumers. */
	version = $state(0);

	#socket: MahjongSocket;
	#dispose: () => void;

	constructor(socket: MahjongSocket) {
		this.#socket = socket;
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
		// no component owns this effect's microtask flush — force it now so both subscriptions
		// are live before the constructor returns, not on the next paint.
		flushSync();
	}

	get socket(): MahjongSocket {
		return this.#socket;
	}

	get seat(): number | null {
		return this.state.seat;
	}

	get claimOffer(): ClientGameState['claimOffer'] {
		return this.state.claimOffer;
	}

	#apply(event: ServerEvent): void {
		if (typeof event.seq === 'number') this.seq = event.seq;
		this.state = reduce(this.state, event);
		if (event.t === 'state_sync') this.#socket.setSeat(event.d.seat);
		this.version++;
	}

	/** Call when the store goes out of scope (e.g. leaving `/table/[id]`) — no component
	 * lifecycle does this automatically. */
	destroy(): void {
		this.#dispose();
	}
}
