<script lang="ts">
	// self-hosted, not a Google Fonts <link> -- the screenshot pipeline shouldn't depend on a
	// third-party CDN being reachable at render time.
	import '@fontsource/schibsted-grotesk/400.css';
	import '@fontsource/schibsted-grotesk/500.css';
	import '@fontsource/schibsted-grotesk/600.css';
	import '@fontsource/schibsted-grotesk/700.css';
	// actually load the CJK fallback: Schibsted has no CJK, so seal/wind/faan glyphs otherwise
	// use the device system font and their side bearings (seal centring) vary by device.
	import '@fontsource/noto-sans-hk/400.css';
	import '@fontsource/noto-sans-hk/500.css';
	import '@fontsource/noto-sans-hk/600.css';
	import '@fontsource/noto-sans-hk/700.css';
	import '@fontsource/noto-sans-hk/800.css';
	import '$lib/styles/app.scss';
	import favicon from '$lib/assets/favicon.svg';
	import TileMuralBackground from '$lib/ui/TileMuralBackground.svelte';
	import ApiConnectGate from '$lib/ui/ApiConnectGate.svelte';
	import { muralVisibility } from '$lib/ui/mural-visibility.svelte';
	import { browser } from '$app/environment';
	import { cleanupStaleTableCredentials, loadClientPrefs } from '$lib/ui/settings-storage';
	import { applyMotionPref } from '$lib/ui/motion';

	// clear abandoned per-table reconnect credentials so they don't sit in localStorage forever.
	cleanupStaleTableCredentials();

	// before children mount, so the mural's one-time motion check already sees it.
	if (browser) applyMotionPref(loadClientPrefs()?.motion ?? 'system');

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<TileMuralBackground visible={muralVisibility.visible} />

<ApiConnectGate>
	{@render children()}
</ApiConnectGate>
