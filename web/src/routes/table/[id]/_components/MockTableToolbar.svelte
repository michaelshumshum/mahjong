<script lang="ts">
	import { MOCK_SCENARIOS } from '$lib/table/mock-game-state';
	import { WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { m } from '$lib/paraglide/messages.js';
	import { MediaQuery } from 'svelte/reactivity';

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

	// phones (and short landscape) collapse the scenario buttons into a disclosure; the same
	// buttons stay inside, so getByRole names keep working once it's open. matches layout.phone-only.
	const compact = new MediaQuery('(max-width: 767px), (max-height: 500px)');
	let pickerOpen = $state(true);
	$effect(() => {
		pickerOpen = !compact.current;
	});
	let activeLabel = $derived(MOCK_SCENARIOS.find((s) => s.id === scenarioId)?.label ?? '');
</script>

<header class="table-toolbar">
	<BackButton label={m.mockTableToolbar_leaveGameLabel()} onclick={onLeaveClick} />

	<details class="scenario-disclosure" bind:open={pickerOpen} data-testid="scenario-disclosure">
		<summary class="scenario-summary">
			<span class="table-label">{m.mockTableToolbar_scenarioLabel()}</span>
			{activeLabel}
		</summary>
		<div
			class="scenario-picker"
			role="group"
			aria-label={m.mockTableToolbar_scenarioGroupAriaLabel()}
		>
			<span class="table-label scenario-picker-label">{m.mockTableToolbar_scenarioLabel()}</span>
			{#each MOCK_SCENARIOS as scenario (scenario.id)}
				<button
					type="button"
					class="scenario-btn"
					class:active={scenario.id === scenarioId}
					aria-pressed={scenario.id === scenarioId}
					onclick={() => {
						scenarioId = scenario.id;
						if (compact.current) pickerOpen = false;
					}}
				>
					{scenario.label}
				</button>
			{/each}
		</div>
	</details>

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
	@use '$lib/styles/layout';

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

	// tablet-up: the disclosure is held open and its summary hidden -- the old flat button row.
	.scenario-summary {
		display: none;

		@include layout.phone-only {
			display: flex;
			align-items: center;
			gap: var(--space-2);
			min-height: var(--tap-target-min);
			padding: var(--space-2) var(--space-3);
			cursor: pointer;
			@include buttons.btn-secondary;
		}
	}

	.scenario-disclosure[open] .scenario-picker {
		@include layout.phone-only {
			margin-top: var(--space-2);
		}
	}

	.scenario-picker-label {
		@include layout.phone-only {
			display: none;
		}
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

		// the hub's compact row already shows wall/prevailing below tablet-up.
		@include layout.phone-only {
			display: none;
		}
	}

	@include layout.phone-only {
		.table-toolbar {
			gap: var(--space-2);
		}

		.chrome-toggles button {
			padding: var(--space-2);
			font-size: var(--font-size-sm);
		}
	}
</style>
