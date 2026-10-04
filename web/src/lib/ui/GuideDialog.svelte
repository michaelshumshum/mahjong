<script lang="ts">
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import TileFace from '$lib/table/TileFace.svelte';
	import CloseButton from './CloseButton.svelte';
	import { faanPatternLabel } from './faan-pattern-labels';
	import { GUIDE_TABS, guideEntries, parseGroup, type GuideTab } from './faan-guide';
	import PanelHeader from './PanelHeader.svelte';

	let { onClose }: { onClose: () => void } = $props();

	let active = $state<GuideTab>(1);
	let entries = $derived(guideEntries(active));
	let showChinese = $derived(getLocale() !== 'zh-Hant');

	function tabLabel(tab: GuideTab): string {
		return tab === 'limit' ? m.guide_tabLimit() : m.guide_tabFaan({ count: tab });
	}

	function onTabKeydown(event: KeyboardEvent, index: number): void {
		const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
		if (step === 0) return;
		event.preventDefault();
		const next = (index + step + GUIDE_TABS.length) % GUIDE_TABS.length;
		active = GUIDE_TABS[next];
		document.getElementById(`guide-tab-${next}`)?.focus();
	}
</script>

<div class="panel-overlay">
	<div
		class="guide-dialog"
		data-testid="guide-dialog"
		role="dialog"
		aria-modal="true"
		aria-labelledby="guide-heading"
	>
		<CloseButton onclick={onClose} />
		<PanelHeader title={m.guide_title()} titleId="guide-heading" />

		<div class="tabs" role="tablist" aria-label={m.guide_tabsLabel()}>
			{#each GUIDE_TABS as tab, i (tab)}
				<button
					type="button"
					role="tab"
					id={`guide-tab-${i}`}
					class="tab"
					class:tab--active={active === tab}
					aria-selected={active === tab}
					aria-controls="guide-panel"
					tabindex={active === tab ? 0 : -1}
					data-testid={`guide-tab-${tab}`}
					onclick={() => (active = tab)}
					onkeydown={(e) => onTabKeydown(e, i)}
				>
					{tabLabel(tab)}
				</button>
			{/each}
		</div>

		<div class="panel" id="guide-panel" role="tabpanel" data-testid="guide-panel">
			<ul class="entries">
				{#each entries as entry (entry.pattern)}
					<li class="entry" data-testid="guide-entry">
						<div class="entry-head">
							<span class="entry-name">{faanPatternLabel(entry.pattern)}</span>
							{#if showChinese}
								<span class="entry-zh">{entry.pattern}</span>
							{/if}
						</div>
						<p class="entry-desc">{entry.description()}</p>
						{#if entry.example.length > 0}
							<div class="example">
								{#each entry.example as group, g (g)}
									<div class="group">
										{#each parseGroup(group) as code, t (t)}
											<span class="tile"><TileFace {code} /></span>
										{/each}
									</div>
								{/each}
							</div>
						{:else}
							<p class="no-example">{m.guide_noExample()}</p>
						{/if}
					</li>
				{/each}
			</ul>
		</div>
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.panel-overlay {
		@include buttons.modal-scrim;
	}

	.guide-dialog {
		position: relative;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: 100%;
		max-width: 40rem;
		max-height: 90dvh;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	.tabs {
		display: flex;
		gap: var(--space-2);
		overflow-x: auto;
		flex-shrink: 0;
	}

	.tab {
		flex-shrink: 0;
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
		@include buttons.btn-secondary;
	}

	.tab--active {
		border-color: var(--color-accent);
		color: var(--color-text);
	}

	.panel {
		overflow-y: auto;
	}

	.entries {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.entry {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
	}

	.entry-head {
		display: flex;
		align-items: baseline;
		gap: var(--space-2);
	}

	.entry-name {
		font-weight: 600;
	}

	.entry-zh {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.entry-desc,
	.no-example {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.no-example {
		font-style: italic;
	}

	.example {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.group {
		display: flex;
		gap: 2px;
	}

	.tile {
		display: inline-block;
		height: 2.75rem;
	}
</style>
