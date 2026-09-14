import type { ServerEvent } from './protocol';

function assertNever(x: never): never {
	throw new Error(`unhandled: ${JSON.stringify(x)}`);
}

/**
 * Pure reducer: server event -> next state. No client game state exists yet
 * (lib/game/store.svelte.ts is a later sub-task), so every case is currently
 * a no-op that returns `state` unchanged. The exhaustive switch is the point:
 * adding a member to ServerEvent without a case here fails the build.
 */
export function reduce<S>(state: S, event: ServerEvent): S {
	switch (event.t) {
		case 'pong':
			return state;
		case 'error':
			console.error('[reducer] server error', event.d.code, event.d.message);
			return state;
		default:
			return assertNever(event);
	}
}
