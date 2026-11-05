<script lang="ts">
	import { page } from '$app/state';
	import { m } from '$lib/paraglide/messages.js';
	import { signInUrl } from '$lib/net/account';

	// a full-page navigation through the api; the callback sends the browser back here
	const href = $derived(signInUrl(page.url.pathname + page.url.search));
</script>

<a class="gsi" {href} data-testid="google-sign-in">
	<svg viewBox="0 0 48 48" aria-hidden="true" focusable="false">
		<path
			fill="#EA4335"
			d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"
		/>
		<path
			fill="#4285F4"
			d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"
		/>
		<path
			fill="#FBBC05"
			d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"
		/>
		<path
			fill="#34A853"
			d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"
		/>
	</svg>
	<span>{m.googleSignInButton_label()}</span>
</a>

<style lang="scss">
	// google's dark-theme button (developers.google.com/identity/branding-guidelines): its
	// colours, logo and roboto medium are brand-mandated, not app tokens
	.gsi {
		display: inline-flex;
		align-items: center;
		align-self: flex-start;
		gap: 10px;
		min-height: var(--tap-target-min);
		padding: 0 var(--space-3);
		border: 1px solid #8e918f;
		border-radius: var(--radius-pill);
		background: #131314;
		color: #e3e3e3;
		font-family: Roboto, Arial, sans-serif;
		font-size: 14px;
		font-weight: 500;
		line-height: 20px;
		letter-spacing: 0.25px;
		text-decoration: none;
		transition: background-color var(--dur-control) ease;

		&:hover {
			background: #1f1f20;
		}

		svg {
			flex: none;
			width: 20px;
			height: 20px;
		}
	}
</style>
