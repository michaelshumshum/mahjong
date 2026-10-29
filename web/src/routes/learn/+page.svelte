<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import { m } from '$lib/paraglide/messages.js';
	import { BAND_LABEL, lessonsByTrack, TRACK_LABEL } from '$lib/learn/lessons';
	import { lessonTitle } from '$lib/learn/lesson-text';
	import { loadProgress, solvedCount } from '$lib/learn/progress';
	import type { LearnProgress } from '$lib/ui/settings-storage';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';

	claimMuralVisible();

	const groups = lessonsByTrack();

	// localStorage only: read after mount so the SSR'd index and its hydration agree (all unsolved).
	let progress = $state<LearnProgress>({});
	$effect(() => {
		progress = loadProgress();
	});
</script>

<svelte:head>
	<title>{m.learn_pageTitle()}</title>
</svelte:head>

<div class="learn-page">
	<header class="page-header">
		<BackButton label={m.learn_backLabel()} href="/" />
		<h1>{m.learn_title()}</h1>
	</header>
	<p class="subtitle">{m.learn_subtitle()}</p>

	{#each groups as group (group.track)}
		{@const ids = group.lessons.map((lesson) => lesson.id)}
		{@const solved = solvedCount(progress, ids)}
		<section class="track" aria-labelledby="track-{group.track}" data-testid="track-{group.track}">
			<header class="track-header">
				<h2 id="track-{group.track}">{TRACK_LABEL[group.track]()}</h2>
				<span
					class="track-count"
					data-testid="track-solved-{group.track}"
					aria-label={m.learn_solvedCountAriaLabel({ solved, total: ids.length })}
					>{m.learn_solvedCount({ solved, total: ids.length })}</span
				>
			</header>
			<ul class="lessons">
				{#each group.lessons as lesson (lesson.id)}
					{@const done = progress[lesson.id]?.solved ?? false}
					<li>
						<a
							class="lesson-card"
							class:lesson-card--solved={done}
							href="/learn/{lesson.id}"
							data-sfx="on"
							data-testid="lesson-card-{lesson.id}"
							data-solved={done}
						>
							<span class="lesson-title">{lessonTitle(lesson)}</span>
							<span class="lesson-meta">
								<span class="band">{BAND_LABEL[lesson.band]()}</span>
								{#if done}
									<span class="solved-mark" title={m.learn_solvedMark()}>
										<CircleCheck size={16} aria-hidden="true" />
										<span class="sr-only">{m.learn_solvedMark()}</span>
									</span>
								{/if}
							</span>
						</a>
					</li>
				{/each}
			</ul>
		</section>
	{/each}
</div>

<style lang="scss">
	@use '$lib/styles/layout';

	.learn-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(60rem, 100%);
		margin: 0 auto;
		padding: var(--space-5);

		@include layout.phone-only {
			padding: var(--space-4);
		}
	}

	.page-header {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-3) var(--space-4);

		h1 {
			margin: 0;
			font-size: var(--font-size-xl);
		}
	}

	.subtitle {
		margin: calc(-1 * var(--space-3)) 0 0;
		color: var(--color-text-muted);
	}

	.track {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.track-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		gap: var(--space-3);
		padding-bottom: var(--space-2);
		border-bottom: 1px solid var(--color-border);

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}
	}

	.track-count {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
	}

	.lessons {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(12rem, 1fr));
		gap: var(--space-3);
		margin: 0;
		padding: 0;
		list-style: none;

		@include layout.phone-only {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	.lesson-card {
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		gap: var(--space-2);
		height: 100%;
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);
		color: var(--color-text);
		text-decoration: none;
		transition: border-color var(--dur-control) ease;

		&:hover {
			border-color: color-mix(in srgb, var(--color-accent) 45%, var(--color-border) 55%);
		}
	}

	.lesson-card--solved {
		border-color: color-mix(in srgb, var(--color-positive) 45%, var(--color-border) 55%);
	}

	.lesson-title {
		font-weight: 600;
	}

	.lesson-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
	}

	.solved-mark {
		display: inline-flex;
		color: var(--color-positive);
	}
</style>
