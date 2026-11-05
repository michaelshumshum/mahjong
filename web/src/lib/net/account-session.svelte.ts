import { accountsEnabled, fetchMe, type Me } from './account';
import { apiBaseUrl } from './lobby';

export type AccountState =
	| { status: 'off' }
	| { status: 'loading' }
	| { status: 'guest' }
	| { status: 'signedIn'; user: Me };

export interface LoadOptions {
	enabled?: boolean;
	baseUrl?: string;
	fetchFn?: typeof fetch;
}

// client-only: ssr never sees the cookie (host-only on the api host), so nothing loads it there
export class AccountSession {
	state = $state<AccountState>({ status: 'loading' });
	user = $derived(this.state.status === 'signedIn' ? this.state.user : null);

	async load({
		enabled = accountsEnabled(),
		baseUrl = apiBaseUrl(),
		fetchFn = fetch
	}: LoadOptions = {}): Promise<void> {
		if (!enabled) {
			this.state = { status: 'off' };
			return;
		}
		try {
			this.setUser(await fetchMe(baseUrl, fetchFn));
		} catch {
			// an unreachable api plays on as a guest, like the ws handshake does
			this.state = { status: 'guest' };
		}
	}

	setUser(user: Me | null): void {
		this.state = user ? { status: 'signedIn', user } : { status: 'guest' };
	}
}

export const accountSession = new AccountSession();
