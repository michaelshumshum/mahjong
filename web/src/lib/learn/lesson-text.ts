import { m } from '$lib/paraglide/messages.js';
import { getLocale } from '$lib/paraglide/runtime.js';
import type { TileCode } from '$lib/table/tile-code';
import { tileName } from '$lib/table/tile-name';
import type { IndexEntry, Lesson } from './generated/lessons';
import { THEME_LABEL } from './lessons';

/** Every value a lesson message may interpolate; each message reads the ones it names. */
export interface LessonTextParams {
	n: number;
	tiles: string;
	count: number;
	faan: number;
}

type LessonMessage = (inputs: LessonTextParams) => string;

export interface LessonText {
	title: LessonMessage;
	prompt: LessonMessage;
	explain: LessonMessage;
}

// keyed by the generated `text` stem (docs/frontend.md §9 "Lesson text"); lessons.spec.ts pins
// it to the index, so a new stem fails there rather than rendering a raw key.
export const LESSON_TEXT: Record<string, LessonText> = {
	basicsIsolatedHonour: {
		title: m.lesson_basicsIsolatedHonour_title,
		prompt: m.lesson_basicsIsolatedHonour_prompt,
		explain: m.lesson_basicsIsolatedHonour_explain
	},
	basicsTwoSidedWait: {
		title: m.lesson_basicsTwoSidedWait_title,
		prompt: m.lesson_basicsTwoSidedWait_prompt,
		explain: m.lesson_basicsTwoSidedWait_explain
	},
	basicsKeepTwoSided: {
		title: m.lesson_basicsKeepTwoSided_title,
		prompt: m.lesson_basicsKeepTwoSided_prompt,
		explain: m.lesson_basicsKeepTwoSided_explain
	},
	basicsPairWait: {
		title: m.lesson_basicsPairWait_title,
		prompt: m.lesson_basicsPairWait_prompt,
		explain: m.lesson_basicsPairWait_explain
	},
	basicsSimpleHand: {
		title: m.lesson_basicsSimpleHand_title,
		prompt: m.lesson_basicsSimpleHand_prompt,
		explain: m.lesson_basicsSimpleHand_explain
	},
	basicsDiscardWin: {
		title: m.lesson_basicsDiscardWin_title,
		prompt: m.lesson_basicsDiscardWin_prompt,
		explain: m.lesson_basicsDiscardWin_explain
	},
	basicsAllCopiesVisible: {
		title: m.lesson_basicsAllCopiesVisible_title,
		prompt: m.lesson_basicsAllCopiesVisible_prompt,
		explain: m.lesson_basicsAllCopiesVisible_explain
	},
	basicsNoChance: {
		title: m.lesson_basicsNoChance_title,
		prompt: m.lesson_basicsNoChance_prompt,
		explain: m.lesson_basicsNoChance_explain
	},
	minedWaits: {
		title: m.lesson_minedWaits_title,
		prompt: m.lesson_minedWaits_prompt,
		explain: m.lesson_minedWaits_explain
	},
	minedEfficiency: {
		title: m.lesson_minedEfficiency_title,
		prompt: m.lesson_minedEfficiency_prompt,
		explain: m.lesson_minedEfficiency_explain
	},
	minedDefenceAllCopiesVisible: {
		title: m.lesson_minedDefenceAllCopiesVisible_title,
		prompt: m.lesson_minedDefenceAllCopiesVisible_prompt,
		explain: m.lesson_minedDefenceAllCopiesVisible_explain
	},
	minedDefenceNoChance: {
		title: m.lesson_minedDefenceNoChance_title,
		prompt: m.lesson_minedDefenceNoChance_prompt,
		explain: m.lesson_minedDefenceNoChance_explain
	},
	minedDefenceGenbutsu: {
		title: m.lesson_minedDefenceGenbutsu_title,
		prompt: m.lesson_minedDefenceGenbutsu_prompt,
		explain: m.lesson_minedDefenceGenbutsu_explain
	},
	minedFaanSelfDraw: {
		title: m.lesson_minedFaanSelfDraw_title,
		prompt: m.lesson_minedFaanSelfDraw_prompt,
		explain: m.lesson_minedFaanSelfDraw_explain
	},
	minedFaanDiscard: {
		title: m.lesson_minedFaanDiscard_title,
		prompt: m.lesson_minedFaanDiscard_prompt,
		explain: m.lesson_minedFaanDiscard_explain
	}
};

export interface TutorialText {
	title: () => string;
	/** keyed by each `narrate`/`expect` step's `text`. */
	steps: Record<string, () => string>;
}

// keyed by the tutorial's `text` stem, listed by hand like LESSON_TEXT; lessons.spec.ts pins it
// to every generated tutorial's steps.
export const TUTORIAL_TEXT: Record<string, TutorialText> = {
	basicsTutorial: {
		title: m.lesson_basicsTutorial_title,
		steps: {
			welcome: m.lesson_basicsTutorial_welcome,
			yourHand: m.lesson_basicsTutorial_yourHand,
			draw: m.lesson_basicsTutorial_draw,
			discardFirst: m.lesson_basicsTutorial_discardFirst,
			pungOffer: m.lesson_basicsTutorial_pungOffer,
			claimPung: m.lesson_basicsTutorial_claimPung,
			pungLaid: m.lesson_basicsTutorial_pungLaid,
			discardAfterPung: m.lesson_basicsTutorial_discardAfterPung,
			chowOffer: m.lesson_basicsTutorial_chowOffer,
			claimChow: m.lesson_basicsTutorial_claimChow,
			discardAfterChow: m.lesson_basicsTutorial_discardAfterChow,
			kongOffer: m.lesson_basicsTutorial_kongOffer,
			claimKong: m.lesson_basicsTutorial_claimKong,
			replacement: m.lesson_basicsTutorial_replacement,
			discardAfterKong: m.lesson_basicsTutorial_discardAfterKong,
			selfDrawn: m.lesson_basicsTutorial_selfDrawn,
			declareWin: m.lesson_basicsTutorial_declareWin,
			result: m.lesson_basicsTutorial_result
		}
	}
};

/** A title needs only the index entry, so the index can render it unloaded: a mined puzzle's
 * theme, else its stem's title with its place in the track. */
export function lessonTitle(entry: IndexEntry): string {
	if (entry.lesson_kind === 'tutorial') return TUTORIAL_TEXT[entry.text].title();
	if (entry.theme) return THEME_LABEL[entry.theme]();
	return LESSON_TEXT[entry.text].title({ n: entry.n, tiles: '', count: 0, faan: 0 });
}

/** The small line under a themed title, so cards sharing a theme can be told apart. Basics
 * and tutorials get none. */
export function lessonSubtitle(entry: IndexEntry): string | null {
	if (entry.lesson_kind === 'tutorial' || !entry.theme) return null;
	return m.learn_puzzleNumber({ n: entry.n });
}

/** Words as a locale list ("East and South"). */
export function localeList(words: readonly string[]): string {
	return new Intl.ListFormat(getLocale(), { type: 'conjunction' }).format(words);
}

/** Tile names as a locale list ("3 Characters and 6 Characters"). */
export function tileList(codes: readonly string[]): string {
	return localeList(codes.map((code) => tileName(code as TileCode)));
}

/** The numbers a lesson's messages interpolate, read off its answer key. */
export function lessonTextParams(lesson: Lesson): LessonTextParams {
	const params: LessonTextParams = { n: lesson.n, tiles: '', count: 0, faan: 0 };
	switch (lesson.kind) {
		case 'count_faan':
			return { ...params, faan: lesson.key.correct };
		case 'best_discard': {
			const best = lesson.key.options.find((o) => o.tile === lesson.key.correct[0]);
			return { ...params, tiles: tileList(lesson.key.correct), count: best?.tiles ?? 0 };
		}
		case 'winning_tiles':
		case 'safe_discard':
			return { ...params, tiles: tileList(lesson.key.correct) };
	}
}
