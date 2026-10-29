import { error } from '@sveltejs/kit';
import { loadLesson } from '$lib/learn/lessons';
import type { PageLoad } from './$types';

// client-only like /table: the puzzle renders the real table, whose state and prefs are
// client-side, so a server render would only be an empty felt to hydrate over.
export const ssr = false;

export const load: PageLoad = async ({ params }) => {
	const lesson = await loadLesson(params.id);
	if (lesson === null) error(404);
	return { lesson };
};
