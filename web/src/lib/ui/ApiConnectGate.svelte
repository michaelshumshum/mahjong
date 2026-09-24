<script lang="ts">
	import type { Snippet } from 'svelte';
	import { page } from '$app/state';
	import { waitForApiHealthy } from '$lib/net/lobby';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';

	let { children }: { children: Snippet } = $props();

	const MIN_DISPLAY_MS = 1000;

	// mock scenarios and /demo are built to run with no backend at all (screenshot pipeline, mock
	// e2e specs -- docs/03-frontend.md's "/table/[id] wiring") -- the gate never applies there.
	let skip = $derived(page.url.searchParams.has('mock') || page.url.pathname.startsWith('/demo'));

	let status = $state<'connecting' | 'ready' | 'error'>('connecting');
	let attempt = $state(0);

	// same panel this screen occupies until `ready` -- shown for the same reason /table/[id]'s
	// own pregame states show it (docs/03-frontend.md §2's "Shared across routes"), released the
	// moment children mount so the underlying page's own claim (lobby, table pregame, ...) takes
	// over cleanly.
	claimMuralVisible(() => !skip && status !== 'ready');

	async function connect(): Promise<void> {
		status = 'connecting';
		attempt = 0;
		const started = Date.now();
		const healthy = await waitForApiHealthy(
			undefined,
			undefined,
			undefined,
			undefined,
			(n) => (attempt = n)
		);
		const elapsed = Date.now() - started;
		if (elapsed < MIN_DISPLAY_MS) {
			await new Promise((resolve) => setTimeout(resolve, MIN_DISPLAY_MS - elapsed));
		}
		status = healthy ? 'ready' : 'error';
	}

	$effect(() => {
		if (skip) return;
		connect();
	});
</script>

{#if skip || status === 'ready'}
	{@render children()}
{:else}
	<div class="connect-gate">
		<div class="connect-panel">
			{#if status === 'connecting'}
				<div class="connect-spinner"></div>
				<p class="connect-status">Connecting…</p>
				{#if attempt > 1}
					<p class="connect-counter">Attempt {attempt}</p>
				{/if}
			{:else}
				<p class="connect-status">Can't reach the server.</p>
				<p class="connect-counter">No response after {attempt} attempts.</p>
				<button type="button" class="connect-retry" onclick={connect}>Retry</button>
			{/if}
		</div>
	</div>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.connect-gate {
		position: fixed;
		inset: 0;
		z-index: var(--z-hud);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100dvh;
	}

	.connect-panel {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		padding: var(--space-6);
		background: var(--color-surface-raised);
		text-align: center;
		@include buttons.panel-elevated;
	}

	.connect-status {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.connect-counter {
		margin: 0;
		font-family: monospace;
		font-size: var(--font-size-xs);
		color: var(--color-text-muted);
	}

	.connect-retry {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-5);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-primary;
	}

	// indeterminate connection spinner, same treatment as /table/[id]'s PretableScreen.
	.connect-spinner {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 3px solid var(--color-border);
		border-top-color: var(--color-accent);
		animation: connect-spin 900ms linear infinite;
	}

	@keyframes connect-spin {
		to {
			transform: rotate(360deg);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.connect-spinner {
			animation: none;
			opacity: 0.6;
		}
	}
</style>
