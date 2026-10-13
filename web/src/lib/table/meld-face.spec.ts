import { describe, expect, it } from 'vitest';
import { meldTileFace } from './meld-face';

describe('meldTileFace', () => {
	it('shows a concealed kong with both end tiles face-down and the middle two face-up', () => {
		const faces = [0, 1, 2, 3].map((i) => meldTileFace('concealed_kong', '5p', i, 4));
		expect(faces).toEqual([null, '5p', '5p', null]);
	});

	it('shows every other meld kind fully face-up', () => {
		for (const kind of ['chow', 'pung', 'exposed_kong', 'added_kong']) {
			const faces = [0, 1, 2, 3].map((i) => meldTileFace(kind, '7m', i, 4));
			expect(faces).toEqual(['7m', '7m', '7m', '7m']);
		}
	});
});
