import type { FairnessState } from '$lib/game/state';

// verified: SHA256(hand_seed || nonce) matches the commit seen before the deal.
// unverifiable: no commit was seen live (history backfill) or no WebCrypto (insecure origin).
export type FairnessCheck = 'verified' | 'mismatch' | 'unverifiable';

function hexToBytes(hex: string): Uint8Array<ArrayBuffer> | null {
	if (hex.length % 2 !== 0 || !/^[0-9a-f]*$/i.test(hex)) return null;
	const out = new Uint8Array(hex.length / 2);
	for (let i = 0; i < out.length; i++) out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
	return out;
}

function bytesToHex(bytes: ArrayBuffer): string {
	return Array.from(new Uint8Array(bytes), (b) => b.toString(16).padStart(2, '0')).join('');
}

export async function checkFairness(fairness: FairnessState): Promise<FairnessCheck> {
	if (fairness.commit === null || typeof crypto === 'undefined' || !crypto.subtle) {
		return 'unverifiable';
	}
	const seed = hexToBytes(fairness.handSeed);
	const nonce = hexToBytes(fairness.nonce);
	if (!seed || !nonce) return 'mismatch';
	const joined = new Uint8Array(seed.length + nonce.length);
	joined.set(seed);
	joined.set(nonce, seed.length);
	const digest = bytesToHex(await crypto.subtle.digest('SHA-256', joined));
	return digest === fairness.commit.toLowerCase() ? 'verified' : 'mismatch';
}
