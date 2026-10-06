import { describe, it, expect } from 'vitest';
import { createToast, removeToast } from './toasts';

describe('createToast/removeToast', () => {
	it('assigns increasing ids across calls', () => {
		const a = createToast('a');
		const b = createToast('b');
		expect(b.id).toBeGreaterThan(a.id);
	});

	it('defaults duration to 4000ms when not given', () => {
		expect(createToast('x').durationMs).toBe(4000);
	});

	it('keeps a given duration', () => {
		expect(createToast('x', 1500).durationMs).toBe(1500);
	});

	it('defaults severity to info', () => {
		expect(createToast('x').severity).toBe('info');
	});

	it('keeps a given severity', () => {
		expect(createToast('x', 4000, 'error').severity).toBe('error');
	});

	it('removeToast filters out only the matching id', () => {
		const a = createToast('a');
		const b = createToast('b');
		expect(removeToast([a, b], a.id)).toEqual([b]);
	});
});
