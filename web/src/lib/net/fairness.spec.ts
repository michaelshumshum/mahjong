import { describe, expect, it } from 'vitest';
import { checkFairness } from './fairness';

async function sha256Hex(bytes: Uint8Array<ArrayBuffer>): Promise<string> {
	const digest = await crypto.subtle.digest('SHA-256', bytes);
	return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('');
}

describe('checkFairness', () => {
	const handSeed = 'aa'.repeat(32);
	const nonce = '0f'.repeat(16);

	it('verifies a reveal that opens the commit', async () => {
		const bytes = new Uint8Array([...Array(32).fill(0xaa), ...Array(16).fill(0x0f)]);
		const commit = await sha256Hex(bytes);
		expect(await checkFairness({ handSeed, nonce, commit })).toBe('verified');
		expect(await checkFairness({ handSeed, nonce, commit: commit.toUpperCase() })).toBe('verified');
	});

	it('flags a reveal that does not open the commit', async () => {
		expect(await checkFairness({ handSeed, nonce, commit: '00'.repeat(32) })).toBe('mismatch');
		expect(await checkFairness({ handSeed: 'zz', nonce, commit: '00' })).toBe('mismatch');
	});

	it('cannot check without a commit seen live', async () => {
		expect(await checkFairness({ handSeed, nonce, commit: null })).toBe('unverifiable');
	});
});
