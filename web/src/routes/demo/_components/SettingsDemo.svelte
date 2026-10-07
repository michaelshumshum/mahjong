<script lang="ts">
	import Settings, { type AutoArm, type ClientPrefs } from '$lib/ui/Settings.svelte';
	import { m } from '$lib/paraglide/messages.js';

	// mock `auto` pre-arm state plus client-only prefs, no real message sent or persisted yet.
	let autoArm = $state<AutoArm>({ noCalls: false, autoPassChow: false });
	let clientPrefs = $state<ClientPrefs>({
		soundEnabled: true,
		motion: 'system',
		discardMode: 'two-step'
	});
	let lastAutoArmSummary = $derived(
		`no_calls=${autoArm.noCalls} auto_pass_chow=${autoArm.autoPassChow}`
	);
	let lastPrefsSummary = $derived(
		`soundEnabled=${clientPrefs.soundEnabled} motion=${clientPrefs.motion}`
	);
</script>

<h2>{m.settingsDemo_heading()}</h2>
<p class="hint">
	{m.settingsDemo_hint()}
</p>
{#if lastAutoArmSummary}
	<p data-testid="auto-arm-summary">{lastAutoArmSummary}</p>
{/if}
{#if lastPrefsSummary}
	<p data-testid="prefs-summary">{lastPrefsSummary}</p>
{/if}
<Settings
	{autoArm}
	prefs={clientPrefs}
	onAutoArmChange={(next) => {
		autoArm = next;
	}}
	onPrefsChange={(next) => {
		clientPrefs = next;
	}}
/>

<style lang="scss">
	.hint {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}
</style>
