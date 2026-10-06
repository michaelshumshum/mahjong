<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import { scheduleAutoDismiss } from './auto-close';
	import type { ConnectionStatus } from '$lib/game/state';

	// a brief drop reads as a glitch, not an outage -- only sustained trouble dims the table.
	// revealDelayMs is a prop, not a constant, so specs can shrink it instead of mocking timers.
	let {
		connection,
		revealDelayMs = 2000
	}: { connection: ConnectionStatus | undefined; revealDelayMs?: number } = $props();

	let visible = $state(false);

	$effect(() => {
		const trouble = connection === 'closed' || connection === 'resyncing';
		if (!trouble) {
			visible = false;
			return;
		}
		const cancel = scheduleAutoDismiss(revealDelayMs, () => (visible = true));
		return cancel;
	});
</script>

{#if visible}
	<div class="connection-banner" role="status" data-testid="connection-banner">
		<div class="card">
			<p class="title">{m.connectionBanner_title()}</p>
			<p class="body">{m.connectionBanner_body()}</p>
		</div>
	</div>
{/if}

<style lang="scss">
	@use '$lib/styles/a11y';

	.connection-banner {
		position: absolute;
		inset: 0;
		z-index: var(--z-overlay);
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgb(0 0 0 / 0.55);
		border-radius: inherit;
		@include a11y.motion-ok {
			animation: connection-banner-in var(--dur-2) var(--ease-out);
		}
	}

	@keyframes connection-banner-in {
		from {
			opacity: 0;
		}
		to {
			opacity: 1;
		}
	}

	.card {
		padding: var(--space-4) var(--space-5);
		border-radius: var(--radius-md);
		background: var(--color-surface-raised);
		color: var(--color-text);
		text-align: center;
		box-shadow: 0 10px 28px rgb(0 0 0 / 0.5);
	}

	.title {
		margin: 0 0 var(--space-1);
		font-weight: 700;
	}

	.body {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
