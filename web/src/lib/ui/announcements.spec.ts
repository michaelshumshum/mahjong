import { describe, expect, it } from 'vitest';
import { announcementsBetween, type AnnounceSnapshot } from './announcements';

function snap(overrides: Partial<AnnounceSnapshot> = {}): AnnounceSnapshot {
	return {
		handKey: 'live:1',
		you: 0,
		names: ['Me', 'Bob', 'Carol', 'Dave'],
		discards: [[], [], [], []],
		meldKinds: [[], [], [], []],
		claim: null,
		yourTurn: false,
		handResult: null,
		...overrides
	};
}

describe('announcementsBetween', () => {
	it('says nothing on the first snapshot or a hand/scenario change', () => {
		const busy = snap({ discards: [['1m'], [], [], []], yourTurn: true });
		expect(announcementsBetween(null, busy, true)).toEqual([]);
		expect(announcementsBetween(snap({ handKey: 'live:0' }), busy, true)).toEqual([]);
	});

	it('skips an ordinary discard by default', () => {
		const next = snap({ discards: [[], ['3s'], [], []] });
		expect(announcementsBetween(snap(), next, false)).toEqual([]);
	});

	it('announces every discard, yours included, when the setting is on', () => {
		const next = snap({ discards: [['1m'], ['3s'], [], []] });
		expect(announcementsBetween(snap(), next, true)).toEqual([
			'You discarded 1 Character',
			'Bob discarded 3 Bamboo'
		]);
	});

	it('announces a claim-relevant discard once, even with every-discard on', () => {
		const prev = snap({ discards: [[], ['3s'], [], []] });
		const next = {
			...prev,
			claim: { kind: 'discard' as const, sourceSeat: 1, tile: '3s' as const }
		};
		expect(announcementsBetween(prev, next, false)).toEqual([
			'Bob discarded 3 Bamboo',
			'You can claim it'
		]);
		expect(announcementsBetween(prev, next, true)).toEqual(['You can claim it']);
	});

	it('announces a robbable kong differently from a discard', () => {
		const next = snap({ claim: { kind: 'kong_rob', sourceSeat: 2, tile: 'z5' } });
		expect(announcementsBetween(snap(), next, false)).toEqual([
			'Carol is adding Red Dragon to a kong',
			'You can claim it'
		]);
	});

	it('announces calls and declarations by seat', () => {
		const next = snap({ meldKinds: [['pung'], [], ['concealed_kong'], ['chow']] });
		expect(announcementsBetween(snap(), next, false)).toEqual([
			'You called Pung',
			'Carol declared Concealed kong',
			'Dave called Chow'
		]);
	});

	it('announces your turn on its rising edge only', () => {
		const turn = snap({ yourTurn: true });
		expect(announcementsBetween(snap(), turn, false)).toEqual(['Your turn']);
		expect(announcementsBetween(turn, turn, false)).toEqual([]);
	});

	it('announces the hand result', () => {
		expect(
			announcementsBetween(snap(), snap({ handResult: { outcome: 'win', winner: 1 } }), false)
		).toEqual(['Bob wins']);
		expect(
			announcementsBetween(snap(), snap({ handResult: { outcome: 'win', winner: 0 } }), false)
		).toEqual(['You win']);
		expect(
			announcementsBetween(
				snap(),
				snap({ handResult: { outcome: 'exhaustive_draw', winner: null } }),
				false
			)
		).toEqual(['Hand ended in a draw']);
	});

	it('names every seat for a spectator (no "you")', () => {
		const prev = snap({ you: -1 });
		const next = { ...prev, discards: [['1m' as const], [], [], []] };
		expect(announcementsBetween(prev, next, true)).toEqual(['Me discarded 1 Character']);
	});
});
