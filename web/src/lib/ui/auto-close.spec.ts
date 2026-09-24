import { describe, it, expect, vi, afterEach } from 'vitest';
import { scheduleAutoDismiss } from './auto-close';

// a one-shot setTimeout, not a ticker, so scheduling logic is testable with fake timers instead
// of waiting out real durationMs.
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
