<script lang="ts">
	// pre-arm toggles sent via `auto` (docs/02-protocol.md §2): `{no_calls?, auto_pass_chow?}`,
	// enforced server-side. No `auto_win` here on purpose — declining a winning claim is a real
	// strategic choice under min_faan rulesets (docs/02-protocol.md "Declining a claim on
	// purpose"), so a win offer always opens a real claim_offer regardless of these toggles. This
	// component is a pure controlled pair of checkboxes, not local game truth: the parent owns
	// the actual values and re-sends `auto` on change.
	export interface AutoArm {
		noCalls: boolean;
		autoPassChow: boolean;
	}

	export type MotionPref = 'system' | 'reduced' | 'full';

	// client-only prefs, no wire equivalent. `motion` overrides `prefers-reduced-motion`
	// (docs/03-frontend.md §8) for a player whose OS setting doesn't match what they want in-game;
	// 'system' (default) just follows the media query.
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
	<h2 id="settings-heading">Settings</h2>

	<fieldset class="group">
		<legend>Pre-arm this hand</legend>
		<label class="toggle">
			<input
				type="checkbox"
				checked={autoArm.noCalls}
				onchange={(e) => onAutoArmChange({ ...autoArm, noCalls: e.currentTarget.checked })}
			/>
			No calls this hand
		</label>
		<label class="toggle">
			<input
				type="checkbox"
				checked={autoArm.autoPassChow}
				onchange={(e) => onAutoArmChange({ ...autoArm, autoPassChow: e.currentTarget.checked })}
			/>
			Auto-pass chow
		</label>
	</fieldset>

	<fieldset class="group">
		<legend>Sound</legend>
		<label class="toggle">
			<input
				type="checkbox"
				checked={prefs.soundEnabled}
				onchange={(e) => onPrefsChange({ ...prefs, soundEnabled: e.currentTarget.checked })}
			/>
			Sound effects
		</label>
	</fieldset>

	<fieldset class="group">
		<legend>Motion</legend>
		{#each MOTION_OPTIONS as option (option.value)}
			<label class="toggle">
				<input
					type="radio"
					name="motion"
					value={option.value}
					checked={prefs.motion === option.value}
					onchange={() => onPrefsChange({ ...prefs, motion: option.value })}
				/>
				{option.label}
			</label>
		{/each}
	</fieldset>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';

	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		max-width: 20rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;
	}

	h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.group {
		display: flex;
		flex-direction: column;
		gap: var(--space-2);
		border: none;
		padding: 0;
		margin: 0;
	}

	legend {
		padding: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-muted);
	}

	.toggle {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		min-height: 44px;
		padding-inline: var(--space-2);
		margin-inline: calc(var(--space-2) * -1);
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: background-color 130ms ease;

		&:hover {
			background: rgb(255 255 255 / 0.06);
		}

		&:active {
			background: rgb(255 255 255 / 0.03);
		}
	}

	input {
		accent-color: var(--color-accent);
		width: 1.05em;
		height: 1.05em;
		cursor: pointer;
	}

	input:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
