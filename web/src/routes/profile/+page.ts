import { redirect } from '@sveltejs/kit';

// the account and games moved into lobby dialogs; old links and sign-in `next`s land there
export function load(): never {
	redirect(307, '/');
}
