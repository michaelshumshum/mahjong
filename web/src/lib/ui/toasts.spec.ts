import { describe, it, expect, vi, afterEach } from 'vitest';
import { createToast, removeToast, scheduleAutoDismiss } from './toasts';

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

	it('removeToast filters out only the matching id', () => {
		const a = createToast('a');
		const b = createToast('b');
		expect(removeToast([a, b], a.id)).toEqual([b]);
	});
});

// the auto-dismiss timer is a one-shot setTimeout, not a ticker, so its scheduling logic is
// testable with fake timers instead of waiting out real durationMs — same "don't rely on real
// elapsed time" goal as timer-ring.spec.ts's pure-math approach, applied via vi.useFakeTimers()
// since the thing under test here is a scheduled side effect, not a derived value.
describe('scheduleAutoDismiss', () => {
	afterEach(() => {
		vi.useRealTimers();
	});

	it('does not fire before durationMs elapses', () => {
		vi.useFakeTimers();
		const onExpire = vi.fn();
		scheduleAutoDismiss(3000, onExpire);
		vi.advanceTimersByTime(2999);
		expect(onExpire).not.toHaveBeenCalled();
	});

	it('fires exactly once at durationMs', () => {
		vi.useFakeTimers();
		const onExpire = vi.fn();
		scheduleAutoDismiss(3000, onExpire);
		vi.advanceTimersByTime(3000);
		expect(onExpire).toHaveBeenCalledOnce();
	});

	it('the returned disposer cancels the timer before it fires', () => {
		vi.useFakeTimers();
		const onExpire = vi.fn();
		const cancel = scheduleAutoDismiss(1000, onExpire);
		cancel();
		vi.advanceTimersByTime(5000);
		expect(onExpire).not.toHaveBeenCalled();
	});
});
