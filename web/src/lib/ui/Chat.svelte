<script module lang="ts">
	// canned-phrase-only, per docs/02-protocol.md §2: `chat` is `{text}`, "rate-limited; consider
	// canned phrases only" — a small fixed list sidesteps both the rate limit and the
	// moderation/anti-toxicity surface a freeform box would open up for a small-scale game. No
	// text input in this component on purpose. Needs `module` (not the instance script) to be a
	// real, importable named export rather than just a component-instance binding.
	export const CANNED_PHRASES = [
		'Good game',
		'Nice hand!',
		'Oops',
		'One moment please',
		'Thanks',
		'Sorry'
	] as const;
</script>

<script lang="ts">
	import type { Seat } from './FaanBreakdown.svelte';

	export interface ChatEntry {
		seat: Seat;
		phrase: string;
		ts: number; // server ts, ms — matches the envelope's `ts` (docs/02-protocol.md §1)
	}

	const SEAT_LABEL: Record<Seat, string> = { 0: 'East', 1: 'South', 2: 'West', 3: 'North' };

	let { messages, onSend }: { messages: ChatEntry[]; onSend: (phrase: string) => void } = $props();

	function formatTime(ts: number): string {
		return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
	}
</script>

<section class="chat" aria-labelledby="chat-heading">
	<h2 id="chat-heading">Chat</h2>

	<ul class="scrollback" role="log" aria-live="polite">
		{#each messages as entry, index (`${index}:${entry.ts}`)}
			<li class="entry">
				<span class="entry-seat">{SEAT_LABEL[entry.seat]}</span>
				<span class="entry-phrase">{entry.phrase}</span>
				<span class="entry-time">{formatTime(entry.ts)}</span>
			</li>
		{/each}
	</ul>

	<div class="picker" role="group" aria-label="Canned phrases">
		{#each CANNED_PHRASES as phrase (phrase)}
			<button type="button" class="phrase-btn" onclick={() => onSend(phrase)}>{phrase}</button>
		{/each}
	</div>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.chat {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		max-width: 20rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.scrollback {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
		max-height: 12rem;
		overflow-y: auto;
	}

	.entry {
		display: flex;
		gap: var(--space-2);
		font-size: var(--font-size-sm);
	}

	// no accent here — cinnabar is reserved for turn/claim-window/win/loss signal, not a
	// per-message label. Weight alone separates the speaker from the phrase.
	.entry-seat {
		font-weight: 600;
	}

	.entry-phrase {
		flex: 1;
	}

	.entry-time {
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.picker {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2);
	}

	.phrase-btn {
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.phrase-btn:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
