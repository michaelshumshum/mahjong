<script lang="ts">
	import { m } from '$lib/paraglide/messages.js';
	import PanelHeader from './PanelHeader.svelte';
	import SegmentedControl from './SegmentedControl.svelte';
	import SwitchRow from './SwitchRow.svelte';
	import LocaleSwitcher from '$lib/i18n/LocaleSwitcher.svelte';
	import { DEFAULT_AUTO_ARM, DEFAULT_CLIENT_PREFS } from './settings-storage';

	// pre-arm toggles sent via `auto`, enforced server-side. No `auto_win` on purpose -- declining
	// a win is a real strategic choice under min_faan rulesets, so it always opens a real claim_offer.
	export interface AutoArm {
		noCalls: boolean;
		autoPassChow: boolean;
	}

	export type MotionPref = 'system' | 'reduced' | 'full';

	// two-step: tap/click lifts a tile, a second tap/Enter on it discards -- lets you see the
	// full tile before committing. one-tap: today's original behaviour.
	export type DiscardMode = 'two-step' | 'one-tap';

	export type TileSize = 'small' | 'medium' | 'large';

	// manual: tiles stay where the player drags them; new tiles join at the right.
	export type HandOrder = 'auto' | 'manual';

	// client-only prefs, no wire equivalent. `haptics` is separate from `motion`: vibration is
	// always feature-detected to mobile, this setting only gates whether it fires at all.
	export interface ClientPrefs {
		soundEnabled: boolean;
		motion: MotionPref;
		discardMode: DiscardMode;
		haptics: boolean;
		// screen-reader verbosity: every discard, not just claim-relevant ones (frontend.md §9).
		announceAllDiscards: boolean;
		tileSize: TileSize;
		handOrder: HandOrder;
	}

	type Tab = 'calls' | 'gameplay' | 'display';

	let {
		autoArm,
		prefs,
		onAutoArmChange,
		onPrefsChange,
		onReset
	}: {
		autoArm: AutoArm;
		prefs: ClientPrefs;
		onAutoArmChange: (next: AutoArm) => void;
		onPrefsChange: (next: ClientPrefs) => void;
		onReset?: () => void;
	} = $props();

	const uid = $props.id();
	const TABS: { id: Tab; label: () => string }[] = [
		{ id: 'calls', label: m.settings_tabCalls },
		{ id: 'gameplay', label: m.settings_tabGameplay },
		{ id: 'display', label: m.settings_tabDisplay }
	];
	let activeTab = $state<Tab>('calls');

	function handleTabKeydown(e: KeyboardEvent): void {
		const index = TABS.findIndex((t) => t.id === activeTab);
		let next: number;
		if (e.key === 'ArrowRight') next = (index + 1) % TABS.length;
		else if (e.key === 'ArrowLeft') next = (index - 1 + TABS.length) % TABS.length;
		else if (e.key === 'Home') next = 0;
		else if (e.key === 'End') next = TABS.length - 1;
		else return;
		e.preventDefault();
		activeTab = TABS[next].id;
		document.getElementById(`${uid}-tab-${activeTab}`)?.focus();
	}

	const isDefault = $derived(
		(Object.keys(DEFAULT_CLIENT_PREFS) as (keyof ClientPrefs)[]).every(
			(k) => prefs[k] === DEFAULT_CLIENT_PREFS[k]
		) &&
			autoArm.noCalls === DEFAULT_AUTO_ARM.noCalls &&
			autoArm.autoPassChow === DEFAULT_AUTO_ARM.autoPassChow
	);

	function reset(): void {
		onAutoArmChange({ ...DEFAULT_AUTO_ARM });
		onPrefsChange({ ...DEFAULT_CLIENT_PREFS });
		onReset?.();
	}
</script>

<section class="settings" aria-labelledby="{uid}-heading">
	<PanelHeader title={m.settings_title()} titleId="{uid}-heading" />

	<div
		class="tabs"
		role="tablist"
		aria-label={m.settings_tabsAriaLabel()}
		onkeydown={handleTabKeydown}
		tabindex="-1"
	>
		{#each TABS as tab (tab.id)}
			<button
				type="button"
				role="tab"
				class="tab"
				id="{uid}-tab-{tab.id}"
				aria-selected={activeTab === tab.id}
				aria-controls="{uid}-panel-{tab.id}"
				tabindex={activeTab === tab.id ? 0 : -1}
				data-testid="settings-tab-{tab.id}"
				onclick={() => (activeTab = tab.id)}
			>
				{tab.label()}
			</button>
		{/each}
	</div>

	<!-- every panel stays rendered (hidden, not unmounted) so tab switches never jump the height -->
	<div class="panels">
		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-calls"
			aria-labelledby="{uid}-tab-calls"
			hidden={activeTab !== 'calls'}
		>
			<fieldset class="group">
				<legend>{m.settings_preArmLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.settings_noCallsLabel()}
						description={m.settings_noCallsDesc()}
						checked={autoArm.noCalls}
						onChange={(checked) => onAutoArmChange({ ...autoArm, noCalls: checked })}
					/>
					<SwitchRow
						label={m.settings_autoPassChowLabel()}
						description={m.settings_autoPassChowDesc()}
						checked={autoArm.autoPassChow}
						onChange={(checked) => onAutoArmChange({ ...autoArm, autoPassChow: checked })}
					/>
				</div>
				<p class="hint">{m.settings_preArmHint()}</p>
			</fieldset>
		</div>

		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-gameplay"
			aria-labelledby="{uid}-tab-gameplay"
			hidden={activeTab !== 'gameplay'}
		>
			<SegmentedControl
				legend={m.settings_discardModeLegend()}
				name="discardMode"
				value={prefs.discardMode}
				options={[
					{
						value: 'two-step',
						label: m.settings_discardModeTwoStepLabel(),
						description: m.settings_discardModeTwoStepDesc()
					},
					{
						value: 'one-tap',
						label: m.settings_discardModeOneTapLabel(),
						description: m.settings_discardModeOneTapDesc()
					}
				]}
				onChange={(discardMode) => onPrefsChange({ ...prefs, discardMode })}
			/>

			<SegmentedControl
				legend={m.settings_handOrderLegend()}
				name="handOrder"
				value={prefs.handOrder}
				options={[
					{
						value: 'auto',
						label: m.settings_handOrderAutoLabel(),
						description: m.settings_handOrderAutoDesc()
					},
					{
						value: 'manual',
						label: m.settings_handOrderManualLabel(),
						description: m.settings_handOrderManualDesc()
					}
				]}
				onChange={(handOrder) => onPrefsChange({ ...prefs, handOrder })}
			/>

			<fieldset class="group">
				<legend>{m.settings_announcementsLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.settings_announceAllDiscardsLabel()}
						description={m.settings_announceAllDiscardsDesc()}
						checked={prefs.announceAllDiscards}
						onChange={(checked) => onPrefsChange({ ...prefs, announceAllDiscards: checked })}
					/>
				</div>
			</fieldset>
		</div>

		<div
			class="panel"
			role="tabpanel"
			id="{uid}-panel-display"
			aria-labelledby="{uid}-tab-display"
			hidden={activeTab !== 'display'}
		>
			<SegmentedControl
				legend={m.settings_tileSizeLegend()}
				name="tileSize"
				value={prefs.tileSize}
				options={[
					{
						value: 'small',
						label: m.settings_tileSizeSmallLabel(),
						description: m.settings_tileSizeSmallDesc()
					},
					{
						value: 'medium',
						label: m.settings_tileSizeMediumLabel(),
						description: m.settings_tileSizeMediumDesc()
					},
					{
						value: 'large',
						label: m.settings_tileSizeLargeLabel(),
						description: m.settings_tileSizeLargeDesc()
					}
				]}
				onChange={(tileSize) => onPrefsChange({ ...prefs, tileSize })}
			/>

			<SegmentedControl
				legend={m.settings_motionLegend()}
				name="motion"
				value={prefs.motion}
				options={[
					{
						value: 'system',
						label: m.settings_motionSystemLabel(),
						description: m.settings_motionSystemDesc()
					},
					{
						value: 'reduced',
						label: m.settings_motionReducedLabel(),
						description: m.settings_motionReducedDesc()
					},
					{
						value: 'full',
						label: m.settings_motionFullLabel(),
						description: m.settings_motionFullDesc()
					}
				]}
				onChange={(motion) => onPrefsChange({ ...prefs, motion })}
			/>

			<fieldset class="group">
				<legend>{m.settings_soundLegend()}</legend>
				<div class="card">
					<SwitchRow
						label={m.settings_soundEffectsLabel()}
						description={m.settings_soundEffectsDesc()}
						checked={prefs.soundEnabled}
						onChange={(checked) => onPrefsChange({ ...prefs, soundEnabled: checked })}
					/>
					<SwitchRow
						label={m.settings_hapticsLabel()}
						description={m.settings_hapticsDesc()}
						checked={prefs.haptics}
						onChange={(checked) => onPrefsChange({ ...prefs, haptics: checked })}
					/>
				</div>
			</fieldset>

			<LocaleSwitcher />
		</div>
	</div>

	<footer class="footer">
		<button
			type="button"
			class="reset-btn"
			data-testid="settings-reset"
			disabled={isDefault}
			onclick={reset}
		>
			{m.settings_resetLabel()}
		</button>
	</footer>
</section>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/forms';
	@use '$lib/styles/layout';
	@use '$lib/styles/a11y';

	// fixed height (capped by the viewport) so switching tabs never resizes the dialog.
	.settings {
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(90vw, 30rem);
		height: min(36rem, calc(100dvh - var(--space-6)));
		padding: var(--space-5) var(--space-5) var(--space-4);
		background: var(--color-surface-raised);
		@include buttons.panel-elevated;

		@include layout.tablet-up {
			padding: var(--space-6) var(--space-6) var(--space-5);
		}

		@include layout.phone-landscape {
			gap: var(--space-2);
			padding: var(--space-3) var(--space-4) var(--space-2);
		}
	}

	.settings :global(h2) {
		@include layout.phone-landscape {
			font-size: var(--font-size-lg);
		}
	}

	// leaves room for DismissablePanel's absolutely positioned close button.
	.settings > :global(.panel-header) {
		padding-inline-end: var(--space-6);
	}

	.tabs {
		display: flex;
		gap: var(--space-1);
		border-bottom: 1px solid var(--color-border);
	}

	.tab {
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

	.panels {
		flex: 1 1 auto;
		min-height: 0;
		overflow-y: auto;
		overscroll-behavior: contain;
		margin-inline: calc(-1 * var(--space-2));
		padding-inline: var(--space-2);
	}

	.panel {
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		padding-block: var(--space-1) var(--space-2);

		&[hidden] {
			display: none;
		}
	}

	.group {
		@include forms.form-group;
		gap: 0;
	}

	legend {
		@include forms.settings-legend;
	}

	.card {
		padding-inline: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
	}

	.hint {
		margin: var(--space-2) 0 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.35;
	}

	.footer {
		display: flex;
		justify-content: flex-end;
		padding-top: var(--space-3);
		border-top: 1px solid var(--color-border);

		@include layout.phone-landscape {
			padding-top: 0;
		}
	}

	.reset-btn {
		@include buttons.btn-ghost;
		min-height: 44px;
		padding: var(--space-2) var(--space-3);
		font: inherit;
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-shadow: none;
		cursor: pointer;
	}
</style>
