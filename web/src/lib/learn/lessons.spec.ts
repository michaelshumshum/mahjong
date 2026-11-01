import { describe, it, expect } from 'vitest';
import settings from '../../../project.inlang/settings.json';
import index from './generated/index.json';
import type { IndexEntry, Lesson, LessonIndexEntry, Tutorial } from './generated/lessons';
import {
	LESSON_TEXT,
	TUTORIAL_TEXT,
	lessonSubtitle,
	lessonTextParams,
	lessonTitle
} from './lesson-text';
import {
	FIRST_TUTORIAL,
	LESSONS,
	THEME_LABEL,
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

	it('lists the tutorials, first, then the puzzles', () => {
		expect(LESSONS).toEqual(entries);
		expect(tutorials.length).toBeGreaterThan(0);
		expect(FIRST_TUTORIAL.id).toBe(tutorials[0].id);
		expect(lessonsByTrack()[0].lessons[0]).toEqual(FIRST_TUTORIAL);
	});

	it('maps every tutorial step to its message', () => {
		const missing = tutorials.flatMap((tutorial) =>
			tutorial.steps.flatMap((step) =>
				step.kind !== 'auto' && !(step.text in (TUTORIAL_TEXT[tutorial.text]?.steps ?? {}))
					? [`${tutorial.text}_${step.text}`]
					: []
			)
		);
		expect(missing).toEqual([]);
		expect(lessonTitle(FIRST_TUTORIAL)).toBe('Your first hand');
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

	it.each(settings.locales)('has a title for every theme in %s', (locale) => {
		const keys = keysByLocale.get(locale)!;
		const camel = (s: string) => s.replace(/(^|_)(\w)/g, (_, __, c: string) => c.toUpperCase());
		const missing = Object.keys(THEME_LABEL)
			.map((theme) => `learn_theme${camel(theme)}`)
			.filter((key) => !keys.has(key));
		expect(missing).toEqual([]);
	});

	it('titles every mined puzzle by its theme, the basics by their own text', () => {
		const mined = lessons.filter((lesson) => lesson.track !== 'basics');
		expect(mined.length).toBeGreaterThan(0);
		for (const lesson of mined) {
			expect(lesson.theme, lesson.id).not.toBeNull();
			expect(lessonTitle(lesson)).toBe(THEME_LABEL[lesson.theme!]());
		}
		expect(lessonTitle(lessonEntry('waits-01')!)).toBe('Two-sided wait');
		const basics = lessons.filter((lesson) => lesson.track === 'basics');
		expect(basics.every((lesson) => lesson.theme === null)).toBe(true);
		expect(lessonTitle(lessonEntry('basics-isolated-honour')!)).toBe('Discard the loner');
	});

	it('tells same-theme cards in a track apart by their subtitle', () => {
		const labels = lessons.map(
			(lesson) => `${lesson.track}|${lessonTitle(lesson)}|${lessonSubtitle(lesson)}`
		);
		expect(new Set(labels).size).toBe(labels.length);
		expect(lessonSubtitle(lessonEntry('waits-03')!)).toBe('Puzzle 3');
		expect(lessonSubtitle(lessonEntry('basics-isolated-honour')!)).toBeNull();
		expect(lessonSubtitle(FIRST_TUTORIAL)).toBeNull();
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
		const lesson = (await loadLesson('basics-isolated-honour')) as Lesson;
		const entry = lessonEntry('basics-isolated-honour') as LessonIndexEntry;
		expect(lesson.kind).toBe(entry.kind);
		expect(lesson.snapshot.t).toBe('state_sync');
	});

	it('loads a tutorial with its start position and steps', async () => {
		const tutorial = (await loadLesson(FIRST_TUTORIAL.id)) as Tutorial;
		expect(tutorial.lesson_kind).toBe('tutorial');
		expect(tutorial.start.t).toBe('state_sync');
		expect(tutorial.steps.length).toBeGreaterThan(0);
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
		const efficiency = (await loadLesson('efficiency-01')) as Lesson;
		const params = lessonTextParams(efficiency);
		expect(params.n).toBe(1);
		expect(params.count).toBeGreaterThan(0);
		expect(LESSON_TEXT[efficiency.text].explain(params)).toContain(String(params.count));
		const faan = (await loadLesson('basics-simple-hand')) as Lesson;
		expect(lessonTextParams(faan).faan).toBe(3);
	});
});
