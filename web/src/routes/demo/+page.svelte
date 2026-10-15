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
	import { m } from '$lib/paraglide/messages.js';
	import { MOCK_SCENARIOS } from '$lib/table/mock-game-state';
	import { PREGAME_PREVIEWS } from '$lib/table/pregame-preview';
	import AnimationDemoPanel from './_components/AnimationDemoPanel.svelte';

	let showAnimationDemo = $state(false);
</script>

<svelte:head>
	<title>{m.demoPage_pageTitle()}</title>
</svelte:head>

<div class="demo-header">
	<BackButton label={m.demoPage_backLabel()} href="/" />
</div>
<h1>{m.demoPage_heading()}</h1>
<p>
	{m.demoPage_docsLinkPrefix()}
	<a href="https://svelte.dev/docs/kit">{m.demoPage_docsLinkText()}</a>
	{m.demoPage_docsLinkSuffix()}
</p>

<section>
	<h2>{m.demoPage_scenariosHeading()}</h2>
	<!-- frozen MOCK_SCENARIOS fixtures, no backend; labels are untranslated fixture strings. -->
	<ul class="demo-links" data-testid="demo-scenarios">
		{#each MOCK_SCENARIOS as scenario (scenario.id)}
			<li><a href="/table/demo?mock={scenario.id}">{scenario.label}</a></li>
		{/each}
	</ul>
	<h2>{m.demoPage_pregameHeading()}</h2>
	<ul class="demo-links">
		{#each PREGAME_PREVIEWS as preview (preview)}
			<li><a href="/table/demo?pregame={preview}">{preview}</a></li>
		{/each}
	</ul>
	<button type="button" class="demo-btn" onclick={() => (showAnimationDemo = true)}
		>{m.demoPage_animateTurnButton()}</button
	>
	{#if showAnimationDemo}
		<AnimationDemoPanel onClose={() => (showAnimationDemo = false)} />
	{/if}
</section>
<section><WsConnectDemo /></section>
<section><TileFaceDemo /></section>
<section><TimerRingDemo /></section>
<section><ClaimButtonsDemo /></section>
<section><FaanBreakdownDemo /></section>
<section><ScoreSheetDemo /></section>
<section><SettingsDemo /></section>
<section><ToastDemo /></section>

<style lang="scss">
	// proves the styles/ partials are usable from a page — not real component styling.
	@use '$lib/styles/layout';
	@use '$lib/styles/buttons';

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

	.demo-links {
		display: flex;
		flex-wrap: wrap;
		gap: var(--space-2) var(--space-4);
		padding: 0;
		list-style: none;
	}

	.demo-btn {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
	}
</style>
