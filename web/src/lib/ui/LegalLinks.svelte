<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';

	// the sign-up dialog opens them in a new tab: navigating away would drop the dialog
	let { newTab = false }: { newTab?: boolean } = $props();

	const target = $derived(newTab ? '_blank' : undefined);
	const rel = $derived(newTab ? 'noopener' : undefined);
</script>

<nav class="legal-links" aria-label={m.legalLinks_label()} data-testid="legal-links">
	<a href="/privacy" {target} {rel} data-testid="legal-link-privacy">{m.legalLinks_privacy()}</a>
	<a href="/terms" {target} {rel} data-testid="legal-link-terms">{m.legalLinks_terms()}</a>
</nav>

<style lang="scss">
	@use '$lib/styles/a11y';

	.legal-links {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1) var(--space-4);
		font-size: var(--font-size-sm);
	}

	a {
		color: var(--color-text-muted);

		&:hover {
			color: var(--color-brass);
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}
</style>
