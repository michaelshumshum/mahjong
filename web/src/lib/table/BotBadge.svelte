<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';

	let { level = null }: { level?: string | null } = $props();

	// level word alone (the chip reads as a bot); mirrors lobby.ts's PRACTICE_DIFFICULTY_TO_TIER,
	// not imported since lobby.ts pulls in $env/dynamic/public. unknown tier -> plain "Bot".
	const LEVEL_LABEL: Record<string, () => string> = {
		T1: m.practiceDifficultySlot_easyLabel,
		T2: m.practiceDifficultySlot_normalLabel,
		T4: m.practiceDifficultySlot_expertLabel,
		ORACLE: m.practiceDifficultySlot_impossibleLabel
	};

	const levelLabel = $derived(level ? LEVEL_LABEL[level]?.() : undefined);
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
