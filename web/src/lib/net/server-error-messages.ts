import { m } from '$lib/paraglide/messages.js';
import type { ErrorCode } from './protocol';

// keyed by the generated `ErrorCode`, so a new server code fails typecheck until translated.
// a code from a newer server than this build falls back to tablePage_serverErrorToast.
const SERVER_ERROR_MESSAGE: Record<ErrorCode, () => string> = {
	bad_frame: m.serverError_badFrame,
	already_joined: m.serverError_alreadyJoined,
	no_such_seat: m.serverError_noSuchSeat,
	seat_taken: m.serverError_seatTaken,
	bad_secret: m.serverError_badSecret,
	not_joined: m.serverError_notJoined,
	table_closed: m.serverError_tableClosed,
	spectators_full: m.serverError_spectatorsFull
};

export function serverErrorToastMessage(code: string, rawMessage: string): string {
	const byCode: Partial<Record<string, () => string>> = SERVER_ERROR_MESSAGE;
	const known = byCode[code];
	return known ? known() : m.tablePage_serverErrorToast({ message: rawMessage });
}
