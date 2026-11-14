import { getLocale } from '$lib/paraglide/runtime.js';

const formatters = new Map<string, Intl.NumberFormat>();

/** A score or payment with its sign: `+25`, `-12`, `0`. */
export function formatSigned(n: number): string {
	const locale = getLocale();
	let formatter = formatters.get(locale);
	if (!formatter) {
		// no grouping: scores read as table counts, never "+1,000"
		formatter = new Intl.NumberFormat(locale, { signDisplay: 'exceptZero', useGrouping: false });
		formatters.set(locale, formatter);
	}
	return formatter.format(n);
}
