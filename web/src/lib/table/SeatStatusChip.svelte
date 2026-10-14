<script lang="ts">
	import type { MockSeatState } from './mock-game-state';
	import { m } from '$lib/paraglide/messages.js';

	let { status }: { status: MockSeatState['status'] } = $props();
</script>

{#if status === 'disconnected'}<span
		class="status-chip status-chip--away"
		title={m.opponentRegion_awayChipTitle()}>{m.opponentRegion_awayChipLabel()}</span
	>{:else if status === 'autoplay'}<span
		class="status-chip status-chip--autoplay"
		title={m.opponentRegion_autoplayChipTitle()}>{m.opponentRegion_autoplayChipLabel()}</span
	>{/if}

<style lang="scss">
	// disconnected/autoplay are transient (unlike the bot badge's fixed identity), so they get a
	// tint, not the bot badge's neutral chrome: error for a seat in trouble, accent for autoplay.
	.status-chip {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 1.25rem;
		padding: 0 0.4rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.status-chip--away {
		border: 1px solid var(--color-status-error);
		color: var(--color-status-error);
		background: rgb(0 0 0 / 0.45);
	}

	.status-chip--autoplay {
		border: 1px solid var(--color-accent);
		color: var(--color-accent-on-dark);
		background: rgb(0 0 0 / 0.45);
	}
</style>
