<script lang="ts">
	import WsConnectDemo from './_components/WsConnectDemo.svelte';
	import TileFaceDemo from './_components/TileFaceDemo.svelte';
	import TimerRingDemo from './_components/TimerRingDemo.svelte';
	import ClaimButtonsDemo from './_components/ClaimButtonsDemo.svelte';
	import FaanBreakdownDemo from './_components/FaanBreakdownDemo.svelte';
	import ScoreSheetDemo from './_components/ScoreSheetDemo.svelte';
	import SettingsDemo from './_components/SettingsDemo.svelte';
	import ToastDemo from './_components/ToastDemo.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';
</script>

<div class="demo-header">
	<BackButton label="Lobby" href="/" />
</div>
<h1>Welcome to SvelteKit</h1>
<p>Visit <a href="https://svelte.dev/docs/kit">svelte.dev/docs/kit</a> to read the documentation</p>

<section><WsConnectDemo /></section>
<section><TileFaceDemo /></section>
<section><TimerRingDemo /></section>
<section><ClaimButtonsDemo /></section>
<section><FaanBreakdownDemo /></section>
<section><ScoreSheetDemo /></section>
<section><SettingsDemo /></section>
<section><ToastDemo /></section>

<style lang="scss">
	// proves the styles/ partials are usable from a page — not real component styling (M4).
	@use '$lib/styles/layout';

	.demo-header {
		display: flex;
		margin-bottom: var(--space-3);
	}

	section {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: var(--space-3);

		@include layout.tablet-up {
			padding: var(--space-5);
		}
	}
</style>
