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
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';

	// google branding (developers.google.com/identity/branding-guidelines): dark fill, unmodified
	// multicolour g and approved wording kept; font, radius, border and motion are the app's own
	.gsi {
		@include buttons.btn-base(var(--space-4));
		display: inline-flex;
		align-items: center;
		align-self: flex-start;
		gap: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: #131314;
		color: #e3e3e3;
		font-weight: 600;
		text-decoration: none;
		box-shadow:
			inset 0 1px 0 rgb(255 255 255 / 0.06),
			0 1px 2px rgb(10 4 2 / 0.35);
		transition:
			transform var(--dur-control) ease,
			border-color var(--dur-control) ease,
			background-color var(--dur-control) ease;

		&:hover {
			border-color: color-mix(in srgb, var(--color-brass) 55%, var(--color-border) 45%);
			background: #1f1f20;
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}

		@include a11y.motion-ok {
			&:hover {
				transform: translateY(-1px);
			}
		}

		svg {
			flex: none;
			width: 18px;
			height: 18px;
		}
	}
</style>
