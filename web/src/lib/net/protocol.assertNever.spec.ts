import { describe, expect, it } from 'vitest';
import { _assertExhaustive } from './protocol.assertNever';
import type { Envelope, ServerEvent } from './protocol';

function baseEvent(): Envelope {
	return { v: 1, ts: 0 };
}

function event(t: ServerEvent['t'], d: unknown): ServerEvent {
	return { ...baseEvent(), t, d } as unknown as ServerEvent;
}

const SERVER_EVENT_CASES: { t: ServerEvent['t']; make: () => ServerEvent }[] = [
	{ t: 'pong', make: () => event('pong', {}) },
	{ t: 'error', make: () => event('error', { message: 'oops' }) },
	{ t: 'state_sync', make: () => event('state_sync', {}) },
	{ t: 'hand_start', make: () => event('hand_start', {}) },
	{ t: 'deal', make: () => event('deal', {}) },
	{ t: 'flower_replace', make: () => event('flower_replace', {}) },
	{ t: 'draw', make: () => event('draw', {}) },
	{ t: 'discard', make: () => event('discard', {}) },
	{ t: 'claim_offer', make: () => event('claim_offer', {}) },
	{ t: 'claim_resolved', make: () => event('claim_resolved', {}) },
	{ t: 'meld', make: () => event('meld', {}) },
	{ t: 'kong_replace', make: () => event('kong_replace', {}) },
	{ t: 'turn', make: () => event('turn', {}) },
	{ t: 'hand_end', make: () => event('hand_end', {}) },
	{ t: 'score', make: () => event('score', {}) },
	{ t: 'game_end', make: () => event('game_end', {}) },
	{ t: 'seat_state', make: () => event('seat_state', {}) },
	{ t: 'server_shutdown', make: () => event('server_shutdown', {}) },
	{ t: 'ack', make: () => event('ack', {}) }
];

describe('_assertExhaustive', () => {
	it('does not throw for any known ServerEvent type', () => {
		for (const { make } of SERVER_EVENT_CASES) {
			expect(() => _assertExhaustive(make())).not.toThrow();
		}
	});

	it('covers every ServerEvent discriminator', () => {
		const handled = new Set(SERVER_EVENT_CASES.map((c) => c.t));
		expect(handled.size).toBe(SERVER_EVENT_CASES.length);
	});

	it('throws when given an unhandled event type', () => {
		const unknown = { ...baseEvent(), t: 'unknown', d: {} } as unknown as ServerEvent;
		expect(() => _assertExhaustive(unknown)).toThrow(/unhandled/);
	});
});
