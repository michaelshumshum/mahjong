<script lang="ts">
	import { onMount, type Snippet } from 'svelte';
	import { page } from '$app/state';
	import { waitForApiHealthy } from '$lib/net/lobby';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import Spinner from '$lib/ui/Spinner.svelte';

	let { children }: { children: Snippet } = $props();

	const MIN_DISPLAY_MS = 1000;

	// ?mock and /demo run with no backend (screenshots, mock e2e: docs/frontend.md "/table/[id]
	// wiring"); /status reports an unreachable api itself, which the gate would hide.
	const skip =
		page.url.searchParams.has('mock') ||
		page.url.pathname.startsWith('/demo') ||
		page.url.pathname.startsWith('/status');

	let status = $state<'connecting' | 'ready' | 'error'>(skip ? 'ready' : 'connecting');
	let attempt = $state(0);
	// set while waiting out a backoff delay; cleared when the next attempt starts. Static "next
	// attempt in Ns" text, not a ticking countdown (web/AGENTS.md's "never a JS ticker" rule).
	let nextRetryDelayMs = $state<number | null>(null);

	// claims mural visibility until `ready` (docs/frontend.md §2's "Shared across routes"),
	// releasing the instant children mount so the underlying page's own claim takes over.
	claimMuralVisible(() => status !== 'ready');

	async function connect(): Promise<void> {
		status = 'connecting';
		attempt = 0;
		nextRetryDelayMs = null;
		const started = Date.now();
		const healthy = await waitForApiHealthy({
			onAttempt: (n) => {
				attempt = n;
				nextRetryDelayMs = null;
			},
			onRetryScheduled: (delayMs) => (nextRetryDelayMs = delayMs)
		});
		const elapsed = Date.now() - started;
		if (elapsed < MIN_DISPLAY_MS) {
			await new Promise((resolve) => setTimeout(resolve, MIN_DISPLAY_MS - elapsed));
		}
		status = healthy ? 'ready' : 'error';
	}

	// fresh page loads only: a client-side navigation must not re-run the check (docs/frontend.md
	// "API health gate").
	onMount(() => {
		if (!skip) connect();
	});
</script>

<!-- the gated page's own title takes over once it mounts. -->
<svelte:head>
	{#if status !== 'ready'}
		<title>{m.lobby_title()}</title>
	{/if}
</svelte:head>

{#if status === 'ready'}
	{@render children()}
{:else}
	<div class="connect-gate">
		<div class="connect-panel">
			{#if status === 'connecting'}
				<Spinner />
				<p class="connect-status">{m.apiConnectGate_connectingStatus()}</p>
				{#if attempt > 1}
					<p class="connect-counter">{m.apiConnectGate_attemptCounter({ attempt })}</p>
				{/if}
				{#if nextRetryDelayMs !== null}
					<p class="connect-counter">
						{m.apiConnectGate_nextAttemptCounter({
							seconds: Math.ceil(nextRetryDelayMs / 1000)
						})}
					</p>
				{/if}
			{:else}
				<p class="connect-status">{m.apiConnectGate_unreachableStatus()}</p>
				<p class="connect-counter">{m.apiConnectGate_noResponseCounter({ attempts: attempt })}</p>
				<button type="button" class="connect-retry" onclick={connect}
					>{m.apiConnectGate_retryButton()}</button
				>
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
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
	}
</style>
