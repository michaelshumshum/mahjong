import { m } from '$lib/paraglide/messages.js';

// ws.py's ErrorPayload.code values, the only ones the server actually sends (grep for them
// there before adding one). An unmapped code falls back to tablePage_serverErrorToast.
const SERVER_ERROR_MESSAGE: Record<string, () => string> = {
	bad_frame: m.serverError_badFrame,
	already_joined: m.serverError_alreadyJoined,
	no_such_seat: m.serverError_noSuchSeat,
	seat_taken: m.serverError_seatTaken,
	bad_secret: m.serverError_badSecret,
	not_joined: m.serverError_notJoined,
	table_closed: m.serverError_tableClosed
};

export function serverErrorToastMessage(code: string, rawMessage: string): string {
	const known = SERVER_ERROR_MESSAGE[code];
	return known ? known() : m.tablePage_serverErrorToast({ message: rawMessage });
}
