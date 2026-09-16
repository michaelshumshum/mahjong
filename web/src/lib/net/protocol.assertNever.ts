// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.
// Compile-time exhaustiveness check (docs/02-protocol.md §6): fails to
// compile if ServerEvent gains a member this switch doesn't handle, or
// if codegen ever regresses `t` from a literal to a widened `string`.
import type { ServerEvent } from './protocol';

function assertNever(x: never): never {
	throw new Error(`unhandled: ${JSON.stringify(x)}`);
}

export function _assertExhaustive(e: ServerEvent): void {
	switch (e.t) {
		case 'pong':
			return;
		case 'error':
			return;
		case 'state_sync':
			return;
		case 'hand_start':
			return;
		case 'deal':
			return;
		case 'flower_replace':
			return;
		case 'draw':
			return;
		case 'discard':
			return;
		case 'claim_offer':
			return;
		case 'claim_resolved':
			return;
		case 'meld':
			return;
		case 'kong_replace':
			return;
		case 'turn':
			return;
		case 'hand_end':
			return;
		case 'score':
			return;
		case 'game_end':
			return;
		case 'seat_state':
			return;
		case 'ack':
			return;
		default:
			assertNever(e);
	}
}
