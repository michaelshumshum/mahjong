<script lang="ts">
	import { MOCK_SCENARIOS } from '$lib/table/mock-game-state';
	import { WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';

	let {
		scenarioId = $bindable(),
		wallCount,
		prevailing,
		onLeaveClick,
		onToggleScoreSheet,
		onToggleSettings,
		onOpenGuide,
		onToggleAnimationDemo
	}: {
		scenarioId: string;
		wallCount: number;
		prevailing: WindLetter;
		onLeaveClick: () => void;
		onToggleScoreSheet: () => void;
		onToggleSettings: () => void;
		onOpenGuide: () => void;
		onToggleAnimationDemo: () => void;
	} = $props();
</script>

<header class="table-toolbar">
	<BackButton label={m.mockTableToolbar_leaveGameLabel()} onclick={onLeaveClick} />

	<div
		class="scenario-picker"
		role="group"
		aria-label={m.mockTableToolbar_scenarioGroupAriaLabel()}
	>
		<span class="table-label">{m.mockTableToolbar_scenarioLabel()}</span>
		{#each MOCK_SCENARIOS as scenario (scenario.id)}
			<button
				type="button"
				class="scenario-btn"
				class:active={scenario.id === scenarioId}
				aria-pressed={scenario.id === scenarioId}
				onclick={() => (scenarioId = scenario.id)}
			>
				{scenario.label}
			</button>
		{/each}
	</div>

	<div class="table-status" aria-label={m.mockTableToolbar_tableStatusAriaLabel()}>
		<span>{m.mockTableToolbar_wallLabel()} <strong>{wallCount}</strong></span>
		<span>{m.mockTableToolbar_prevailingLabel()} <strong>{WIND_CHAR[prevailing]}</strong></span>
	</div>

	<div class="chrome-toggles">
		<button type="button" data-testid="open-guide" onclick={onOpenGuide}
			>{m.tableToolbar_guideButton()}</button
		>
		<button type="button" data-testid="toggle-score-sheet" onclick={onToggleScoreSheet}
			>{m.mockTableToolbar_scoreSheetButton()}</button
		>
		<button type="button" data-testid="toggle-settings" onclick={onToggleSettings}
			>{m.mockTableToolbar_settingsButton()}</button
		>
		<button type="button" onclick={onToggleAnimationDemo}
			>{m.mockTableToolbar_animateATurnButton()}</button
		>
	</div>
</header>

<style lang="scss">
	@use '$lib/styles/buttons';

	.table-toolbar {
		display: flex;
		flex-wrap: wrap;
		justify-content: space-between;
		gap: var(--space-3);
		z-index: var(--z-hud);
	}

	.scenario-picker,
	.chrome-toggles {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
	}

	.table-label {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.scenario-btn,
	.chrome-toggles button {
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
	}

	// same secondary-button family as the chrome toggles -- only the active scenario stands out.
	.scenario-btn {
		@include buttons.btn-secondary;
	}

	.scenario-btn.active {
		@include buttons.btn-primary;
	}

	.chrome-toggles button {
		@include buttons.btn-secondary;
	}

	.table-status {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
		font-variant-numeric: tabular-nums;

		strong {
			color: var(--color-text);
		}
	}
</style>
