<script lang="ts" generics="T extends string">
	// tabs follow the wai-aria tablist pattern; panels stay in the owner, wired by
	// `${idPrefix}-tab-${id}` / `${idPrefix}-panel-${id}`.
	let {
		tabs,
		active,
		idPrefix,
		label,
		testidPrefix,
		onChange
	}: {
		tabs: { id: T; label: string; flag?: string }[];
		active: T;
		idPrefix: string;
		label: string;
		testidPrefix: string;
		onChange: (next: T) => void;
	} = $props();

	function handleKeydown(e: KeyboardEvent): void {
		const index = tabs.findIndex((t) => t.id === active);
		let next: number;
		if (e.key === 'ArrowRight') next = (index + 1) % tabs.length;
		else if (e.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = tabs.length - 1;
		else return;
		e.preventDefault();
		onChange(tabs[next].id);
		document.getElementById(`${idPrefix}-tab-${tabs[next].id}`)?.focus();
	}
</script>

<div class="tabs" role="tablist" aria-label={label} onkeydown={handleKeydown} tabindex="-1">
	{#each tabs as tab (tab.id)}
		<button
			type="button"
			role="tab"
			class="tab"
			id="{idPrefix}-tab-{tab.id}"
			aria-selected={active === tab.id}
			aria-controls="{idPrefix}-panel-{tab.id}"
			tabindex={active === tab.id ? 0 : -1}
			data-testid="{testidPrefix}-{tab.id}"
			onclick={() => onChange(tab.id)}
		>
			{tab.label}
			{#if tab.flag}<span class="flag" aria-hidden="true"></span><span class="sr-only"
					>{tab.flag}</span
				>{/if}
		</button>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/a11y';

	.tabs {
		display: flex;
		gap: var(--space-1);
		border-bottom: 1px solid var(--color-border);
	}

	.tab {
		position: relative;
		flex: 1 1 0;
		min-height: 44px;
		padding: var(--space-2) var(--space-2);
		margin-bottom: -1px;
		border: none;
		border-bottom: 2px solid transparent;
		background: none;
		color: var(--color-text-muted);
		font: inherit;
		font-size: var(--font-size-sm);
		font-weight: 700;
		cursor: pointer;

		@include a11y.motion-ok {
			transition:
				color 130ms ease,
				border-color 130ms ease;
		}

		&:hover {
			color: var(--color-text);
		}

		&[aria-selected='true'] {
			border-bottom-color: var(--color-brass);
			color: var(--color-text);
		}
	}

	.flag {
		display: inline-block;
		width: 0.45rem;
		height: 0.45rem;
		margin-inline-start: var(--space-1);
		border-radius: 50%;
		background: var(--color-status-error);
		vertical-align: super;
	}

	.sr-only {
		@include a11y.sr-only;
	}
</style>
