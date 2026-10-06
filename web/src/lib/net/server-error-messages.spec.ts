import { describe, it, expect } from 'vitest';
import { serverErrorToastMessage } from './server-error-messages';

describe('serverErrorToastMessage', () => {
	it('maps a known code to its human message, ignoring the raw wire message', () => {
		expect(serverErrorToastMessage('bad_secret', 'wrong secret for seat 2')).toBe(
			"Couldn't reconnect to your seat -- it may have been taken over."
		);
	});

	it('maps every known server/app/ws.py code', () => {
		for (const code of [
			'bad_frame',
			'already_joined',
			'no_such_seat',
			'seat_taken',
			'bad_secret',
			'not_joined'
		]) {
			expect(serverErrorToastMessage(code, 'x')).not.toContain('Server error');
		}
	});

	it('falls back to the raw wire message for an unknown code', () => {
		expect(serverErrorToastMessage('some_future_code', 'a new kind of failure')).toBe(
			'Server error: a new kind of failure'
		);
	});
});
