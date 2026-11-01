import { error } from '@sveltejs/kit';
import { isBand, isPuzzleKind } from '$lib/learn/kinds';
import type { PageLoad } from './$types';

// client-only like /learn/[id]: the puzzle is fetched and rendered on the real table.
export const ssr = false;

export const load: PageLoad = ({ url }) => {
	const kind = url.searchParams.get('kind');
	const band = url.searchParams.get('band') ?? 'beginner';
	if (!isPuzzleKind(kind) || !isBand(band)) error(404);
	return { kind, band };
};
