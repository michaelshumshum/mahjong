<script lang="ts">
	import type { Snippet } from 'svelte';
	import { env } from '$env/dynamic/public';
	import { m } from '$lib/paraglide/messages.js';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import BackButton from './BackButton.svelte';
	import LegalLinks from './LegalLinks.svelte';
	import { claimMuralVisible } from './mural-visibility.svelte';
	import { ISSUES_URL, contactEmail, effectiveDateLabel } from './site-links';

	// /privacy and /terms: one reading column over the mural (docs/frontend.md §7)
	let {
		pageTitle,
		title,
		summary,
		testId,
		children
	}: { pageTitle: string; title: string; summary: string; testId: string; children: Snippet } =
		$props();

	claimMuralVisible();

	const email = contactEmail(env.PUBLIC_CONTACT_EMAIL);
</script>

<svelte:head>
	<title>{pageTitle}</title>
</svelte:head>

<div class="legal-page" data-testid={testId}>
	<header class="page-header">
		<BackButton label={m.legalPage_backLabel()} href="/" />
		<h1>{title}</h1>
		<p class="effective" data-testid="legal-effective">
			{m.legalPage_effective({ date: effectiveDateLabel(getLocale()) })}
		</p>
	</header>

	<article class="sheet">
		<p class="summary">{summary}</p>
		{@render children()}
		<section>
			<h2>{m.legalPage_contactHeading()}</h2>
			<p>
				{m.legalPage_contactLead()}
				{#if email}
					<a href="mailto:{email}" data-testid="legal-contact">{email}</a>
				{:else}
					<a href={ISSUES_URL} rel="noopener noreferrer" data-testid="legal-contact"
						>{m.legalPage_contactIssues()}</a
					>
				{/if}
			</p>
		</section>
	</article>

	<LegalLinks />
</div>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.legal-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(44rem, 100%);
		margin: 0 auto;
		padding: var(--space-5);

		@include layout.phone-only {
			padding: var(--space-4);
		}
	}

	.page-header {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2) var(--space-4);

		h1 {
			margin: 0;
			margin-inline-end: auto;
			font-size: var(--font-size-xl);
		}
	}

	.effective {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.sheet {
		padding: var(--space-5) var(--space-6);
		background: var(--color-surface-raised);
		line-height: 1.6;
		@include buttons.panel-elevated;

		@include layout.phone-only {
			padding: var(--space-4);
		}

		:global(section) {
			margin-top: var(--space-6);
		}

		:global(h2) {
			margin: 0 0 var(--space-2);
			font-size: var(--font-size-base);
			font-weight: 700;
		}

		:global(p),
		:global(ul),
		:global(dl) {
			max-width: 38rem;
			margin: 0 0 var(--space-3);
		}

		:global(ul) {
			padding-inline-start: var(--space-5);
		}

		:global(li + li) {
			margin-top: var(--space-2);
		}

		:global(a) {
			color: var(--color-accent-on-dark);
		}
	}

	// the one accent: the plain-language version, ahead of the detail
	.summary {
		padding-inline-start: var(--space-4);
		border-inline-start: 3px solid var(--color-brass);
		font-size: var(--font-size-base);
		font-weight: 500;
	}
</style>
