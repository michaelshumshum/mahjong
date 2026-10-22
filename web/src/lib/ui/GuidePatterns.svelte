<script lang="ts">
	import { tick } from 'svelte';
	import { getLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import TileFace from '$lib/table/TileFace.svelte';
	import type { RuleSet } from '$lib/net/ruleset';
	import { faanPatternLabel } from './faan-pattern-labels';
	import {
		guideTabs,
		isKeyGroup,
		matchesQuery,
		paidFaan,
		parseGroup,
		type GuideTab,
		type GuideTag,
		type ScoredEntry
	} from './faan-guide';

	let {
		entries,
		rules,
		focus = $bindable(null)
	}: {
		entries: ScoredEntry[];
		// the rules `entries` were scored under; null = defaults, no cap
		rules: RuleSet | null;
		// pattern to scroll to and mark
		focus?: string | null;
	} = $props();

	let filter = $state<GuideTab | 'all'>('all');
	let query = $state('');
	let listEl: HTMLElement | undefined = $state();

	let showChinese = $derived(getLocale() !== 'zh-Hant');
	let tabs = $derived(guideTabs(entries));
	let searching = $derived(query.trim() !== '');
	let visible = $derived(
		searching
			? entries.filter((e) => matchesQuery(e, query))
			: filter === 'all'
				? entries
				: entries.filter((e) => e.tab === filter)
	);
	let groups = $derived(
		guideTabs(visible).map((tab) => ({ tab, entries: visible.filter((e) => e.tab === tab) }))
	);
	let listed = $derived(new Set(entries.map((e) => e.pattern)));

	const TAG_LABEL: Record<GuideTag, () => string> = {
		situational: m.guide_tagSituational,
		concealed: m.guide_tagConcealed,
		flowers: m.guide_tagFlowers
	};

	function tabLabel(tab: GuideTab): string {
		return tab === 'limit' ? m.guide_tabLimit() : m.guide_tabFaan({ count: tab });
	}

	function badge(entry: ScoredEntry): string {
		const faan = paidFaan(entry, rules);
		return entry.limit ? m.guide_badgeLimit({ faan }) : m.guide_tabFaan({ count: faan });
	}

	// a filter that the rules in view emptied falls back to everything
	$effect(() => {
		if (filter !== 'all' && !tabs.includes(filter)) filter = 'all';
	});

	$effect(() => {
		const target = focus;
		if (target === null || !listed.has(target)) return;
		query = '';
		filter = 'all';
		void tick().then(() => {
			const el = listEl?.querySelector<HTMLElement>(`[data-pattern="${target}"]`);
			el?.scrollIntoView({ block: 'center' });
			el?.focus({ preventScroll: true });
		});
	});
</script>

<div class="patterns-view">
	<input
		class="search"
		type="search"
		placeholder={m.guide_searchPlaceholder()}
		aria-label={m.guide_searchLabel()}
		data-testid="guide-search"
		bind:value={query}
	/>

	{#if !searching}
		<div class="filters" role="group" aria-label={m.guide_tabsLabel()}>
			<button
				type="button"
				class="chip"
				aria-pressed={filter === 'all'}
				data-testid="guide-tab-all"
				onclick={() => (filter = 'all')}>{m.guide_tabAll()}</button
			>
			{#each tabs as tab (tab)}
				<button
					type="button"
					class="chip"
					aria-pressed={filter === tab}
					data-testid={`guide-tab-${tab}`}
					onclick={() => (filter = tab)}>{tabLabel(tab)}</button
				>
			{/each}
		</div>
	{:else}
		<p class="result-count" aria-live="polite">
			{m.guide_searchCount({ count: visible.length })}
		</p>
	{/if}

	<div class="panel" data-testid="guide-panel" bind:this={listEl}>
		{#each groups as group (group.tab)}
			<section class="group-section" aria-labelledby={`guide-group-${group.tab}`}>
				<h3 class="group-heading" id={`guide-group-${group.tab}`}>{tabLabel(group.tab)}</h3>
				<ul class="entries">
					{#each group.entries as entry (entry.pattern)}
						<li
							class="entry"
							class:entry--focus={focus === entry.pattern}
							data-testid="guide-entry"
							data-pattern={entry.pattern}
							tabindex="-1"
						>
							<div class="entry-head">
								<span class="entry-name">{faanPatternLabel(entry.pattern)}</span>
								{#if showChinese}
									<span class="entry-zh">{entry.pattern}</span>
								{/if}
								<span class="entry-faan" data-testid="guide-entry-faan">{badge(entry)}</span>
								{#if entry.faan !== entry.defaultFaan}
									<span class="entry-default"
										>{m.guide_badgeDefault({ faan: entry.defaultFaan })}</span
									>
								{/if}
							</div>
							{#if entry.tags}
								<ul class="tags">
									{#each entry.tags as tag (tag)}
										<li class="tag tag--{tag}">{TAG_LABEL[tag]()}</li>
									{/each}
								</ul>
							{/if}
							<p class="entry-desc">{entry.description()}</p>
							{#if entry.example.length > 0}
								<div class="example">
									{#each entry.example as group, g (g)}
										<div class="tile-group" class:tile-group--key={isKeyGroup(group)}>
											{#each parseGroup(group) as code, t (t)}
												<span class="tile"><TileFace {code} /></span>
											{/each}
										</div>
									{/each}
								</div>
							{/if}
							{#if entry.related?.some((p) => listed.has(p))}
								<p class="related">
									<span>{m.guide_relatedLabel()}</span>
									{#each entry.related.filter((p) => listed.has(p)) as other (other)}
										<button
											type="button"
											class="related-link"
											data-testid="guide-related"
											onclick={() => (focus = other)}>{faanPatternLabel(other)}</button
										>
									{/each}
								</p>
							{/if}
						</li>
					{/each}
				</ul>
			</section>
		{:else}
			<p class="empty">{m.guide_searchEmpty()}</p>
		{/each}
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.patterns-view {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		flex: 1;
		min-height: 0;
	}

	.search {
		flex-shrink: 0;
		font: inherit;
		min-height: 36px;
		padding: var(--space-1) var(--space-3);
		color: var(--color-text);
		@include buttons.input-recessed;
	}

	.filters {
		display: flex;
		gap: var(--space-2);
		overflow-x: auto;
		flex-shrink: 0;
		padding-bottom: 2px;
	}

	.chip {
		flex-shrink: 0;
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
		min-height: 32px;

		&[aria-pressed='true'] {
			border-color: var(--color-brass);
			color: var(--color-text);
		}
	}

	.result-count {
		margin: 0;
		flex-shrink: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.panel {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
	}

	.group-heading {
		position: sticky;
		top: 0;
		z-index: 1;
		margin: 0 0 var(--space-2);
		padding-block: var(--space-1);
		font-size: var(--font-size-sm);
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--color-brass);
		background: var(--color-surface-raised);
		border-bottom: 1px solid var(--color-border);
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
		padding: var(--space-2);
		margin: calc(-1 * var(--space-2));
		border-radius: var(--radius-sm);
		scroll-margin-top: var(--space-6);
	}

	.entry--focus {
		background: color-mix(in srgb, var(--color-brass) 10%, transparent);
		box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--color-brass) 55%, transparent);
	}

	.entry-head {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-2);
	}

	.entry-name {
		font-weight: 600;
	}

	.entry-zh,
	.entry-default {
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.entry-faan {
		margin-inline-start: auto;
		padding: 0 var(--space-2);
		border-radius: var(--radius-pill);
		font-size: var(--font-size-sm);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--color-brass);
		background: color-mix(in srgb, var(--color-brass) 14%, transparent);
	}

	.entry-default {
		flex-basis: 100%;
		text-align: end;
	}

	.tags {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-1);
		margin: 0;
		padding: 0;
		list-style: none;
	}

	.tag {
		padding: 0 var(--space-2);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-pill);
		font-size: var(--font-size-xs);
		color: var(--color-text-muted);
	}

	.entry-desc {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.example {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-3);
	}

	.tile-group {
		display: flex;
		gap: 2px;
		padding: 2px;
		border-radius: var(--radius-sm);
	}

	// the group the pattern is about; the rest of the hand is context
	.tile-group--key {
		box-shadow: 0 0 0 2px var(--color-brass);
	}

	.example:has(.tile-group--key) .tile-group:not(.tile-group--key) {
		opacity: 0.6;
	}

	.tile {
		display: inline-block;
		height: 2.75rem;
	}

	.related {
		display: flex;
		flex-wrap: wrap;
		align-items: baseline;
		gap: var(--space-1) var(--space-2);
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.related-link {
		padding: 0;
		border: 0;
		background: none;
		font: inherit;
		color: var(--color-text);
		text-decoration: underline dotted;
		text-underline-offset: 3px;
		cursor: pointer;

		&:hover {
			color: var(--color-brass);
		}
	}

	.empty {
		margin: 0;
		color: var(--color-text-muted);
	}

	// two columns of cards; examples shrink so a 14-tile hand still fits one column
	@container guide-view (min-width: 46rem) {
		.entries {
			display: grid;
			grid-template-columns: repeat(2, minmax(0, 1fr));
			gap: var(--space-4) var(--space-6);
		}

		.tile {
			height: 2.25rem;
		}

		.example {
			gap: var(--space-2);
		}
	}
</style>
