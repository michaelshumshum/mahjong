// `/table/[id]?pregame=<preview>` values; /demo links to each.
export const PREGAME_PREVIEWS = ['connecting', 'join', 'waiting'] as const;
export type PregamePreview = (typeof PREGAME_PREVIEWS)[number];
