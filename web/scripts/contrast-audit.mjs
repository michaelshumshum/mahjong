#!/usr/bin/env node
// contrast audit for docs/frontend.md §8: wcag ratios of text tokens against the backgrounds they
// actually sit on (alpha layers composited). usage: node scripts/contrast-audit.mjs (from web/)
import { readFileSync } from 'node:fs';

const hex = (h) => {
	h = h.replace('#', '');
	return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16));
};
const over = (fg, a, bg) => fg.map((c, i) => c * a + bg[i] * (1 - a));
const lin = (c) => {
	c /= 255;
	return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};
const L = ([r, g, b]) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
const ratio = (a, b) => {
	const [x, y] = [L(a), L(b)].sort((p, q) => q - p);
	return (x + 0.05) / (y + 0.05);
};
const mix = (a, pct, b) => a.map((c, i) => c * pct + b[i] * (1 - pct));
const tokens = readFileSync(new URL('../src/lib/styles/_tokens.scss', import.meta.url), 'utf8');
const T = Object.fromEntries(
	[...tokens.matchAll(/--color-([a-z-]+):\s*#([0-9a-f]{6});/g)].map(([, k, v]) => [k, hex(v)])
);
const black = [0, 0, 0];
// mural: an ivory tile face under brightness(0.42) saturate(0.55), then the scrim.
const sat = (c, s) => {
	const l = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
	return c.map((v) => l + (v - l) * s);
};
const tileLit = sat(
	T.tile.map((c) => c * 0.42),
	0.55
);
const mural = (a) => over(black, a, tileLit);
const rows = [
	['text-muted', 'surface-raised', T['text-muted'], T['surface-raised'], 4.5],
	['text-muted', 'surface', T['text-muted'], T.surface, 4.5],
	['text-muted', 'bg', T['text-muted'], T.bg, 4.5],
	['felt-muted', 'felt-lit (lightest felt)', T['felt-muted'], T['felt-lit'], 4.5],
	['text-on-felt', 'felt-lit', T['text-on-felt'], T['felt-lit'], 4.5],
	['text-muted', 'mural, scrim 0.72 (centre)', T['text-muted'], mural(0.72), 4.5],
	['text-muted', 'mural, scrim 0.52 (75%)', T['text-muted'], mural(0.52), 4.5],
	['text-muted', 'mural, scrim 0.5 (edge)', T['text-muted'], mural(0.5), 4.5],
	['text', 'mural, scrim 0.5 (edge)', T.text, mural(0.5), 4.5],
	[
		'bot badge text-muted (felt override)',
		'surface-raised',
		T['felt-muted'],
		T['surface-raised'],
		4.5
	],
	[
		'status-chip away (status-error)',
		'black 45% on felt-lit',
		T['status-error'],
		over(black, 0.45, T['felt-lit']),
		4.5
	],
	[
		'status-chip autoplay (accent-on-dark)',
		'black 45% on felt-lit',
		T['accent-on-dark'],
		over(black, 0.45, T['felt-lit']),
		4.5
	],
	['dealer badge text', 'accent 85% + black', T.text, mix(T.accent, 0.85, black), 4.5],
	[
		'hub min-faan chip (felt-muted)',
		'black 12% on felt-lit',
		T['felt-muted'],
		over(black, 0.12, T['felt-lit']),
		4.5
	],
	['toast text', 'surface-raised', T.text, T['surface-raised'], 4.5],
	['toast warn icon (status-error)', 'surface-raised', T['status-error'], T['surface-raised'], 3],
	[
		'toast error icon (accent-on-dark)',
		'surface-raised',
		T['accent-on-dark'],
		T['surface-raised'],
		3
	],
	['toast info icon (text-muted)', 'surface-raised', T['text-muted'], T['surface-raised'], 3],
	[
		'+ delta chip',
		'positive 16% on surface-raised',
		T.positive,
		mix(T.positive, 0.16, T['surface-raised']),
		4.5
	],
	[
		'- delta chip',
		'negative 14% on surface-raised',
		T.negative,
		mix(T.negative, 0.14, T['surface-raised']),
		4.5
	],
	[
		'+ score-delta float',
		'black 55% pill on felt-lit',
		T.positive,
		over(black, 0.55, T['felt-lit']),
		4.5
	],
	[
		'- score-delta float',
		'black 55% pill on felt-lit',
		T.negative,
		over(black, 0.55, T['felt-lit']),
		4.5
	],
	['connection pill (accent-on-dark)', 'bg', T['accent-on-dark'], T.bg, 4.5],
	['score-sheet round toggle hover (accent-on-dark)', 'bg', T['accent-on-dark'], T.bg, 4.5],
	['open-table chip (positive)', 'surface', T.positive, T.surface, 4.5]
];
const out = rows.map(([fg, bg, f, b, need]) => ({
	fg,
	bg,
	ratio: ratio(f, b).toFixed(2),
	need,
	pass: ratio(f, b) >= need
}));
console.log(out.map((r) => `| ${r.fg} | ${r.bg} | ${r.ratio} | ${r.need} |`).join('\n'));

if (out.some((r) => !r.pass)) process.exitCode = 1;
