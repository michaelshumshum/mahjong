<script lang="ts">
	import PanelHeader from './PanelHeader.svelte';
	import FormGroup from './FormGroup.svelte';
	import OptionRow from './OptionRow.svelte';

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

	const MOTION_OPTIONS: { value: MotionPref; label: string }[] = [
		{ value: 'system', label: 'Match system' },
		{ value: 'reduced', label: 'Reduce motion' },
		{ value: 'full', label: 'Full motion' }
	];
</script>

<section class="settings" aria-labelledby="settings-heading">
	<PanelHeader title="Settings" badge="Preferences" />

	<FormGroup legend="Pre-arm this hand">
		<OptionRow
			type="checkbox"
			label="No calls this hand"
			checked={autoArm.noCalls}
			onChange={(checked) => onAutoArmChange({ ...autoArm, noCalls: checked })}
		/>
		<OptionRow
			type="checkbox"
			label="Auto-pass chow"
			checked={autoArm.autoPassChow}
			onChange={(checked) => onAutoArmChange({ ...autoArm, autoPassChow: checked })}
		/>
	</FormGroup>

	<FormGroup legend="Sound">
		<OptionRow
			type="checkbox"
			label="Sound effects"
			checked={prefs.soundEnabled}
			onChange={(checked) => onPrefsChange({ ...prefs, soundEnabled: checked })}
		/>
	</FormGroup>

	<FormGroup legend="Motion">
		{#each MOTION_OPTIONS as option (option.value)}
			<OptionRow
				type="radio"
				name="motion"
				value={option.value}
				label={option.label}
				checked={prefs.motion === option.value}
				onChange={() => onPrefsChange({ ...prefs, motion: option.value })}
			/>
		{/each}
	</FormGroup>
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
