import { describe, expect, it } from 'vitest';
import { formatGameDate, modeLabel, seatName } from './my-games';

describe('my games formatting', () => {
	it('labels both modes and leaves an unrecorded one out', () => {
		expect(modeLabel('practice')).toBe('Practice');
		expect(modeLabel('multiplayer')).toBe('Multiplayer');
		expect(modeLabel(null)).toBeNull();
	});

	it('names a seat, an unnamed one as a guest', () => {
		expect(seatName({ seat: 0, kind: 'user', name: 'Bob', bot_tier: null })).toBe('Bob');
		expect(seatName({ seat: 0, kind: 'guest', name: null, bot_tier: null })).toBe('Guest');
	});

	it('formats the end time in the given locale', () => {
		const iso = '2026-11-05T09:30:00Z';
		const en = formatGameDate(iso, 'en');
		expect(en).toContain('2026');
		expect(en).toContain('Nov');
		expect(formatGameDate(iso, 'zh-Hant')).toContain('11月');
	});
});
