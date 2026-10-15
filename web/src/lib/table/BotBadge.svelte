<script lang="ts">
	import { TIER_LABEL } from '$lib/net/practice-difficulty';
	import type { BotTier } from '$lib/net/protocol';
	import { m } from '$lib/paraglide/messages.js';

	let { level = null }: { level?: BotTier | null } = $props();

	// level word alone (the chip reads as a bot). unknown tier -> plain "Bot".
	const levelLabel = $derived(level ? TIER_LABEL[level]?.() : undefined);
</script>

<span
	class="bot-badge"
	data-level={level ?? undefined}
	title={levelLabel ? m.botBadge_levelTitle({ level: levelLabel }) : m.botBadge_title()}
	>{levelLabel ?? m.botBadge_label()}</span
>

<style lang="scss">
	// persistent identity marker, not transient like dealer/turn -- a quiet chip, not --color-accent.
	.bot-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		height: 1.25rem;
		padding: 0 0.4rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface-raised);
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		white-space: nowrap;
	}
</style>
