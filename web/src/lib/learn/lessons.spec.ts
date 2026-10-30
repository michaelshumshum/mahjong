import { describe, it, expect } from 'vitest';
import settings from '../../../project.inlang/settings.json';
import index from './generated/index.json';
import type { IndexEntry, LessonIndexEntry, Tutorial } from './generated/lessons';
import { LESSON_TEXT, lessonTextParams } from './lesson-text';
import {
	LESSONS,
	TRACKS,
	lessonEntry,
	lessonsByTrack,
	loadLesson,
	nextLesson,
	previousLesson
} from './lessons';

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

const entries = index as IndexEntry[];
const lessons = entries.filter((e): e is LessonIndexEntry => e.lesson_kind === 'puzzle');

const generated = import.meta.glob<Tutorial>('./generated/*.json', {
	eager: true,
	import: 'default'
});
const tutorials = entries
	.filter((e) => e.lesson_kind === 'tutorial')
	.map((e) => generated[`./generated/${e.id}.json`]);

describe('generated lessons', () => {
	it('has lessons', () => {
		expect(lessons.length).toBeGreaterThan(0);
	});

	it('lists only puzzles until tutorials have a player', () => {
		expect(LESSONS).toEqual(lessons);
		expect(tutorials.length).toBeGreaterThan(0);
	});

	it.each(settings.locales)('has every tutorial title and step key in %s', (locale) => {
		const keys = keysByLocale.get(locale)!;
		const missing = tutorials.flatMap((tutorial) =>
			['title', ...tutorial.steps.flatMap((step) => (step.kind === 'auto' ? [] : [step.text]))]
				.map((part) => `lesson_${tutorial.text}_${part}`)
				.filter((key) => !keys.has(key))
		);
		expect(missing).toEqual([]);
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

	it('maps every text stem to its messages', () => {
		expect(lessons.map((lesson) => lesson.text).filter((text) => !(text in LESSON_TEXT))).toEqual(
			[]
		);
	});

	it.each(settings.locales)('has a label for every track and band in %s', (locale) => {
		const keys = keysByLocale.get(locale)!;
		const capitalize = (s: string) => s[0].toUpperCase() + s.slice(1);
		for (const lesson of entries) {
			expect(keys.has(`learn_track${capitalize(lesson.track)}`), lesson.track).toBe(true);
			expect(keys.has(`learn_band${capitalize(lesson.band)}`), lesson.band).toBe(true);
		}
	});
});

describe('lesson loading', () => {
	it('groups lessons by track in the fixed track order, index order within', () => {
		const groups = lessonsByTrack();
		expect(groups.map((g) => g.track)).toEqual([...TRACKS]);
		expect(groups.flatMap((g) => g.lessons)).toHaveLength(LESSONS.length);
		for (const group of groups) {
			expect(group.lessons.every((lesson) => lesson.track === group.track)).toBe(true);
			const ns = group.lessons.map((lesson) => lesson.n);
			expect(ns).toEqual(ns.toSorted((a, b) => a - b));
		}
	});

	it('drops tracks with no lessons', () => {
		const only = LESSONS.filter((lesson) => lesson.track === 'waits');
		expect(lessonsByTrack(only).map((g) => g.track)).toEqual(['waits']);
	});

	it('walks the index with next and previous, across tracks', () => {
		const ordered = lessonsByTrack().flatMap((g) => g.lessons);
		const first = ordered[0];
		const last = ordered[ordered.length - 1];
		expect(previousLesson(first.id)).toBeNull();
		expect(nextLesson(first.id)).toEqual(ordered[1]);
		expect(previousLesson(ordered[1].id)).toEqual(first);
		expect(nextLesson(last.id)).toBeNull();
		const lastBasics = lessonsByTrack()[0].lessons.at(-1)!;
		expect(nextLesson(lastBasics.id)?.track).toBe(lessonsByTrack()[1].track);
		expect(nextLesson('no-such-lesson')).toBeNull();
	});

	it('loads one lesson by id, matching its index entry', async () => {
		const lesson = await loadLesson('basics-isolated-honour');
		expect(lesson).not.toBeNull();
		expect(lesson!.kind).toBe(lessonEntry('basics-isolated-honour')!.kind);
		expect(lesson!.snapshot.t).toBe('state_sync');
	});

	it('loads every indexed lesson', async () => {
		for (const entry of LESSONS) {
			const lesson = await loadLesson(entry.id);
			expect(lesson?.id, entry.id).toBe(entry.id);
		}
	});

	it('returns null for an unknown id, including the index file itself', async () => {
		expect(await loadLesson('no-such-lesson')).toBeNull();
		expect(await loadLesson('index')).toBeNull();
	});

	it('interpolates key numbers into the lesson text', async () => {
		const efficiency = (await loadLesson('efficiency-01'))!;
		const params = lessonTextParams(efficiency);
		expect(params.n).toBe(1);
		expect(params.count).toBeGreaterThan(0);
		expect(LESSON_TEXT[efficiency.text].explain(params)).toContain(String(params.count));
		const faan = (await loadLesson('basics-simple-hand'))!;
		expect(lessonTextParams(faan).faan).toBe(3);
	});
});
