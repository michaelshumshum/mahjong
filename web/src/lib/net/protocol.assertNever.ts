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
		default:
			assertNever(e);
	}
}
