import { describe, it, expect } from 'vitest';
import settings from '../../../project.inlang/settings.json';
import index from './generated/index.json';
import type { LessonIndexEntry } from './generated/lessons';

const files = import.meta.glob<Record<string, unknown>>('../../../messages/*/learn.json', {
	eager: true,
	import: 'default'
});

const keysByLocale = new Map(
	Object.entries(files).map(([path, messages]) => [
		path.split('/').at(-2)!,
		new Set(Object.keys(messages))
	])
);

const lessons: LessonIndexEntry[] = index as LessonIndexEntry[];

describe('generated lessons', () => {
	it('has lessons', () => {
		expect(lessons.length).toBeGreaterThan(0);
	});

	it.each(settings.locales)('has every lesson text key in %s', (locale) => {
		const keys = keysByLocale.get(locale)!;
		const missing = lessons.flatMap((lesson) =>
			['title', 'prompt', 'explain']
				.map((part) => `lesson_${lesson.text}_${part}`)
				.filter((key) => !keys.has(key))
		);
		expect(missing).toEqual([]);
	});

	it.each(settings.locales)('has a label for every track and band in %s', (locale) => {
		const keys = keysByLocale.get(locale)!;
		const capitalize = (s: string) => s[0].toUpperCase() + s.slice(1);
		for (const lesson of lessons) {
			expect(keys.has(`learn_track${capitalize(lesson.track)}`), lesson.track).toBe(true);
			expect(keys.has(`learn_band${capitalize(lesson.band)}`), lesson.band).toBe(true);
		}
	});
});
