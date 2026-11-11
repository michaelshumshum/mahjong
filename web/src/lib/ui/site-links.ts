export const SOURCE_REPO_URL = 'https://github.com/michaelshumshum/mahjong';
export const ISSUES_URL = `${SOURCE_REPO_URL}/issues`;

// the date /privacy and /terms took effect; change it with their wording
export const LEGAL_EFFECTIVE_DATE = '2026-11-11';

/** `PUBLIC_CONTACT_EMAIL`'s value, or null when unset or blank (docs/infra.md §2). */
export function contactEmail(raw: string | undefined): string | null {
	return raw?.trim() || null;
}

/** `LEGAL_EFFECTIVE_DATE` as a long date in `locale`; UTC so SSR and hydration agree. */
export function effectiveDateLabel(locale: string): string {
	return new Date(`${LEGAL_EFFECTIVE_DATE}T00:00:00Z`).toLocaleDateString(locale, {
		dateStyle: 'long',
		timeZone: 'UTC'
	});
}
