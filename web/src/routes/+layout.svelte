<script lang="ts">
	// self-hosted (not a Google Fonts <link>): the Playwright screenshot pipeline and any
	// offline dev environment shouldn't depend on a third-party CDN being reachable at
	// render time. Only the weights actually used (400 body, 500/600 labels, 700 headings).
	import '@fontsource/schibsted-grotesk/400.css';
	import '@fontsource/schibsted-grotesk/500.css';
	import '@fontsource/schibsted-grotesk/600.css';
	import '@fontsource/schibsted-grotesk/700.css';
	import '$lib/styles/app.scss';
	import favicon from '$lib/assets/favicon.svg';
	import TileMuralBackground from '$lib/ui/TileMuralBackground.svelte';
	import { muralVisibility } from '$lib/ui/mural-visibility.svelte';
	import { cleanupStaleTableCredentials } from '$lib/ui/settings-storage';

	// clear abandoned per-table reconnect credentials on every app load so a disconnect-and-never
	// return doesn't leave secrets in localStorage forever.
	cleanupStaleTableCredentials();

	let { children } = $props();
</script>

<svelte:head>
	<link rel="icon" href={favicon} />
</svelte:head>

<TileMuralBackground visible={muralVisibility.visible} />

{@render children()}
