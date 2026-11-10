import type { AccountState } from '$lib/net/account-session.svelte';

// per page load: "not now" holds until a reload, then a nameless guest is asked again
let dismissed = false;

export function dismissWelcome(): void {
	dismissed = true;
}

/** Whether the lobby asks a nameless guest to sign in or pick a name (docs/frontend.md §7 "Lobby"). */
export function shouldPromptWelcome(
	status: AccountState['status'],
	guestName: string | null,
	url: URL
): boolean {
	if (dismissed) return false;
	if (status !== 'guest' && status !== 'off') return false;
	if (guestName?.trim()) return false;
	// a sign-in callback's own dialog (SigninReturn) owns this load
	return !url.searchParams.has('signin') && !url.searchParams.has('signup');
}

export function resetWelcomeForTests(): void {
	dismissed = false;
}
