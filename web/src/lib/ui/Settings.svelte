<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import PanelHeader from './PanelHeader.svelte';
	import FormGroup from './FormGroup.svelte';
	import OptionRow from './OptionRow.svelte';
	import LocaleSwitcher from '$lib/i18n/LocaleSwitcher.svelte';

	// pre-arm toggles sent via `auto`, enforced server-side. No `auto_win` on purpose --
	// declining a winning claim is a real strategic choice under min_faan rulesets, so a win
	// offer always opens a real claim_offer regardless. Pure controlled checkboxes, not truth.
	export interface AutoArm {
		noCalls: boolean;
		autoPassChow: boolean;
	}

	export type MotionPref = 'system' | 'reduced' | 'full';

	// client-only prefs, no wire equivalent. `motion` overrides `prefers-reduced-motion` for a
	// player whose OS setting doesn't match what they want in-game.
	export interface ClientPrefs {
		soundEnabled: boolean;
		motion: MotionPref;
	}

	let {
		autoArm,
		prefs,
		onAutoArmChange,
		onPrefsChange
	}: {
		autoArm: AutoArm;
		prefs: ClientPrefs;
		onAutoArmChange: (next: AutoArm) => void;
		onPrefsChange: (next: ClientPrefs) => void;
	} = $props();

	const MOTION_OPTIONS: { value: MotionPref; label: () => string }[] = [
		{ value: 'system', label: m.settings_motionSystemLabel },
		{ value: 'reduced', label: m.settings_motionReducedLabel },
		{ value: 'full', label: m.settings_motionFullLabel }
	];
</script>

<section class="settings" aria-labelledby="settings-heading">
	<PanelHeader title={m.settings_title()} badge={m.settings_badge()} />

	<FormGroup legend={m.settings_preArmLegend()}>
		<OptionRow
			type="checkbox"
			label={m.settings_noCallsLabel()}
			checked={autoArm.noCalls}
			onChange={(checked) => onAutoArmChange({ ...autoArm, noCalls: checked })}
		/>
		<OptionRow
			type="checkbox"
			label={m.settings_autoPassChowLabel()}
			checked={autoArm.autoPassChow}
			onChange={(checked) => onAutoArmChange({ ...autoArm, autoPassChow: checked })}
		/>
	</FormGroup>

	<FormGroup legend={m.settings_soundLegend()}>
		<OptionRow
			type="checkbox"
			label={m.settings_soundEffectsLabel()}
			checked={prefs.soundEnabled}
			onChange={(checked) => onPrefsChange({ ...prefs, soundEnabled: checked })}
		/>
	</FormGroup>

	<FormGroup legend={m.settings_motionLegend()}>
		{#each MOTION_OPTIONS as option (option.value)}
			<OptionRow
				type="radio"
				name="motion"
				value={option.value}
				label={option.label()}
				checked={prefs.motion === option.value}
				onChange={() => onPrefsChange({ ...prefs, motion: option.value })}
			/>
		{/each}
	</FormGroup>

	<LocaleSwitcher />
</section>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(90vw, 28rem);
		max-width: 90vw;
		padding: var(--space-5);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6);
		}
	}
</style>
