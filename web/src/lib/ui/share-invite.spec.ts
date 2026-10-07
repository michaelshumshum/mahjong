import { describe, it, expect, vi } from 'vitest';
import { shareOrCopy } from './share-invite';

const DATA = { url: 'https://example.test/table/ABC123', title: 't', text: 'x' };

function clipboard(ok = true) {
	return {
		writeText: vi.fn(() => (ok ? Promise.resolve() : Promise.reject(new Error('denied'))))
	} as unknown as Clipboard;
}

describe('shareOrCopy', () => {
	it('uses the share sheet when available', async () => {
		const share = vi.fn(() => Promise.resolve());
		const cb = clipboard();
		expect(await shareOrCopy(DATA, { share, clipboard: cb })).toBe('shared');
		expect(share).toHaveBeenCalledWith(DATA);
		expect(cb.writeText).not.toHaveBeenCalled();
	});

	it('treats a dismissed share sheet as cancelled, without copying', async () => {
		const share = vi.fn(() => Promise.reject(new DOMException('no', 'AbortError')));
		const cb = clipboard();
		expect(await shareOrCopy(DATA, { share, clipboard: cb })).toBe('cancelled');
		expect(cb.writeText).not.toHaveBeenCalled();
	});

	it('falls back to the clipboard when share throws for another reason', async () => {
		const share = vi.fn(() => Promise.reject(new DOMException('no', 'NotAllowedError')));
		const cb = clipboard();
		expect(await shareOrCopy(DATA, { share, clipboard: cb })).toBe('copied');
		expect(cb.writeText).toHaveBeenCalledWith(DATA.url);
	});

	it('copies the url when there is no share sheet', async () => {
		const cb = clipboard();
		expect(await shareOrCopy(DATA, { clipboard: cb })).toBe('copied');
	});

	it('skips share when canShare rejects the payload', async () => {
		const share = vi.fn(() => Promise.resolve());
		const cb = clipboard();
		const result = await shareOrCopy(DATA, { share, canShare: () => false, clipboard: cb });
		expect(result).toBe('copied');
		expect(share).not.toHaveBeenCalled();
	});

	it('reports failure when the clipboard is blocked too', async () => {
		expect(await shareOrCopy(DATA, { clipboard: clipboard(false) })).toBe('failed');
	});
});
