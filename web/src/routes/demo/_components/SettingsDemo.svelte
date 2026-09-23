<script lang="ts">
	import Settings, { type AutoArm, type ClientPrefs } from '$lib/ui/Settings.svelte';

	// Settings demo (this sub-task): mock `auto` pre-arm state plus client-only prefs, no real
	// `auto` message sent and no prefs persisted anywhere yet.
	let autoArm = $state<AutoArm>({ noCalls: false, autoPassChow: false });
	let clientPrefs = $state<ClientPrefs>({ soundEnabled: true, motion: 'system' });
	let lastAutoArmSummary = $derived(
		`no_calls=${autoArm.noCalls} auto_pass_chow=${autoArm.autoPassChow}`
	);
	let lastPrefsSummary = $derived(
		`soundEnabled=${clientPrefs.soundEnabled} motion=${clientPrefs.motion}`
	);
</script>

<h2>Settings demo</h2>
<p class="hint">
	Pre-arm toggles mirror the `auto` message's `no_calls`/`auto_pass_chow` fields
	(docs/02-protocol.md §2) — no `auto_win`, per that section's "Declining a claim on purpose".
	Sound/motion are client-only prefs stubbed ahead of the real settings surface.
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
