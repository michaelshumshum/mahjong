<script lang="ts">
	import { MOCK_SCENARIOS } from '$lib/table/mock-game-state';
	import { WIND_CHAR, type WindLetter } from '$lib/table/wind';
	import BackButton from '$lib/ui/BackButton.svelte';

	let {
		scenarioId = $bindable(),
		wallCount,
		prevailing,
		onLeaveClick,
		onToggleScoreSheet,
		onToggleSettings,
		onToggleAnimationDemo
	}: {
		scenarioId: string;
		wallCount: number;
		prevailing: WindLetter;
		onLeaveClick: () => void;
		onToggleScoreSheet: () => void;
		onToggleSettings: () => void;
		onToggleAnimationDemo: () => void;
	} = $props();
</script>

<header class="table-toolbar">
	<BackButton label="Leave game" onclick={onLeaveClick} />

	<div class="scenario-picker" role="group" aria-label="Mock scenario">
		<span class="table-label">Scenario</span>
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

	<div class="table-status" aria-label="Table status">
		<span>Wall <strong>{wallCount}</strong></span>
		<span>Prevailing <strong>{WIND_CHAR[prevailing]}</strong></span>
	</div>

	<div class="chrome-toggles">
		<button type="button" onclick={onToggleScoreSheet}>Score sheet</button>
		<button type="button" onclick={onToggleSettings}>Settings</button>
		<button type="button" onclick={onToggleAnimationDemo}>Animate a turn</button>
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
