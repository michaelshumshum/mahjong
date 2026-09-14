import { describe, it, expect, vi } from 'vitest';
import { reduce } from './reducer';
import type { ServerEvent } from './protocol';

describe('reduce', () => {
	it('is a no-op stub for pong (no client game store yet)', () => {
		const state = { marker: 'unchanged' };
		const event: ServerEvent = { v: 1, ts: 1, seq: 1, t: 'pong', d: { t0: 10, t1: 20 } };

		expect(reduce(state, event)).toBe(state);
	});

	it('logs and no-ops for error events', () => {
		const spy = vi.spyOn(console, 'error').mockImplementation(() => {});
		const state = { marker: 'unchanged' };
		const event: ServerEvent = {
			v: 1,
			ts: 1,
			seq: 1,
			t: 'error',
			d: { code: 'bad_frame', message: 'boom' }
		};

		expect(reduce(state, event)).toBe(state);
		expect(spy).toHaveBeenCalledWith('[reducer] server error', 'bad_frame', 'boom');
		spy.mockRestore();
	});
});
