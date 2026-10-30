<script lang="ts">
	import PuzzlePage from './_components/PuzzlePage.svelte';
	import TutorialPage from './_components/TutorialPage.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
</script>

{#if data.lesson.lesson_kind === 'tutorial'}
	{#key data.lesson.id}
		<TutorialPage tutorial={data.lesson} />
	{/key}
{:else}
	<PuzzlePage lesson={data.lesson} />
{/if}
