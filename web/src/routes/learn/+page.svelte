<script lang="ts">
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import { m } from '$lib/paraglide/messages.js';
	import { ENDLESS_TITLE, endlessScore, saveEndlessBand } from '$lib/learn/endless';
	import type { Band, IndexEntry } from '$lib/learn/generated/lessons';
	import { BANDS, PUZZLE_KINDS } from '$lib/learn/kinds';
	import {
		BAND_LABEL,
		FIRST_TUTORIAL,
		lessonsByBand,
		lessonsByTrack,
		TRACK_BLURB,
		TRACK_LABEL
	} from '$lib/learn/lessons';
	import { lessonSubtitle, lessonTitle } from '$lib/learn/lesson-text';
	import { firstUnsolved, loadProgress, solvedCount } from '$lib/learn/progress';
	import {
		loadLearnEndless,
		type LearnEndless,
		type LearnProgress
	} from '$lib/ui/settings-storage';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';
	import SegmentedControl from '$lib/ui/SegmentedControl.svelte';

	claimMuralVisible();

	const groups = lessonsByTrack().map((group) => ({
		...group,
		tutorials: group.lessons.filter((lesson) => lesson.lesson_kind === 'tutorial'),
		bands: lessonsByBand(group.lessons)
	}));

	// localStorage only: read after mount so the SSR'd index and its hydration agree (all unsolved).
	let progress = $state<LearnProgress>({});
	let endless = $state<LearnEndless>({ band: 'beginner', scores: {} });
	$effect(() => {
		progress = loadProgress();
		endless = loadLearnEndless();
	});
	let band = $derived(endless.band);
	// the tutorial leads until it's solved; after that, the first unsolved lesson does.
	let next = $derived(firstUnsolved(progress));
	let tutorialSolved = $derived(progress[FIRST_TUTORIAL.id]?.solved ?? false);

	function pickBand(value: Band): void {
		endless = { ...endless, band: value };
		saveEndlessBand(value);
	}
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

	{#if tutorialSolved && next}
		{@const subtitle = lessonSubtitle(next)}
		<a
			class="lesson-card lead-card"
			href="/learn/{next.id}"
			data-sfx="on"
			data-testid="learn-continue"
		>
			<span class="eyebrow">{m.learn_continueLabel()}</span>
			<span class="lesson-title"
				>{m.learn_continueLesson({
					track: TRACK_LABEL[next.track](),
					title: lessonTitle(next)
				})}</span
			>
			{#if subtitle}
				<span class="lesson-sub">{subtitle}</span>
			{/if}
		</a>
	{:else if tutorialSolved}
		<p class="all-solved" data-testid="learn-all-solved">
			<CircleCheck size={18} aria-hidden="true" />
			<span>{m.learn_allSolved()}</span>
			<a href="#endless">{m.learn_allSolvedEndless()}</a>
		</p>
	{/if}

	{#each groups as group (group.track)}
		{@const ids = group.lessons.map((lesson) => lesson.id)}
		{@const solved = solvedCount(progress, ids)}
		<section class="track" aria-labelledby="track-{group.track}" data-testid="track-{group.track}">
			<header class="track-header">
				<h2 id="track-{group.track}">{TRACK_LABEL[group.track]()}</h2>
				<span class="track-progress">
					<span
						class="track-bar"
						role="progressbar"
						aria-label={m.learn_trackProgressAriaLabel({ track: TRACK_LABEL[group.track]() })}
						aria-valuemin={0}
						aria-valuemax={ids.length}
						aria-valuenow={solved}
						aria-valuetext={m.learn_solvedCountAriaLabel({ solved, total: ids.length })}
						data-testid="track-bar-{group.track}"
						style:--fill="{(solved / ids.length) * 100}%"
					></span>
					<span class="track-count" data-testid="track-solved-{group.track}" aria-hidden="true"
						>{m.learn_solvedCount({ solved, total: ids.length })}</span
					>
				</span>
			</header>
			<p class="track-blurb">{TRACK_BLURB[group.track]()}</p>
			{#if group.tutorials.length > 0}
				<ul class="lessons">
					{#each group.tutorials as lesson (lesson.id)}
						<li class="tutorial-item">{@render card(lesson, false)}</li>
					{/each}
				</ul>
			{/if}
			{#each group.bands as bandGroup (bandGroup.band)}
				<h3 class="band-heading" data-testid="band-{group.track}-{bandGroup.band}">
					{BAND_LABEL[bandGroup.band]()}
				</h3>
				<ul class="lessons">
					{#each bandGroup.lessons as lesson (lesson.id)}
						<li>{@render card(lesson, bandGroup.numbered.has(lesson.id))}</li>
					{/each}
				</ul>
			{/each}
		</section>
	{/each}

	{@render endlessSection()}
</div>

{#snippet card(lesson: IndexEntry, numbered: boolean)}
	{@const done = progress[lesson.id]?.solved ?? false}
	{@const tutorial = lesson.lesson_kind === 'tutorial'}
	{@const subtitle = numbered ? lessonSubtitle(lesson) : null}
	<a
		class="lesson-card"
		class:lesson-card--solved={done}
		class:lesson-card--tutorial={tutorial}
		href="/learn/{lesson.id}"
		data-sfx="on"
		data-testid="lesson-card-{lesson.id}"
		data-solved={done}
	>
		{#if tutorial}
			<span class="eyebrow">{done ? m.learn_tutorialLabel() : m.learn_tutorialStartHere()}</span>
		{/if}
		<span class="lesson-heading">
			<span class="lesson-title">{lessonTitle(lesson)}</span>
			{#if subtitle}
				<span class="lesson-sub" data-testid="lesson-sub-{lesson.id}">{subtitle}</span>
			{/if}
		</span>
		{#if done}
			<span class="solved-mark" title={m.learn_solvedMark()}>
				<CircleCheck size={16} aria-hidden="true" />
				<span class="sr-only">{m.learn_solvedMark()}</span>
			</span>
		{/if}
	</a>
{/snippet}

{#snippet endlessSection()}
	<section id="endless" class="track endless" aria-labelledby="endless-title" data-testid="endless">
		<header class="track-header">
			<h2 id="endless-title">{m.learn_endlessHeading()}</h2>
		</header>
		<p class="track-blurb">{m.learn_endlessIntro()}</p>
		<div class="band-picker" data-testid="endless-band">
			<SegmentedControl
				legend={m.learn_endlessBandLabel()}
				name="endless-band"
				options={BANDS.map((option) => ({ value: option, label: BAND_LABEL[option]() }))}
				value={band}
				onChange={pickBand}
			/>
		</div>
		<ul class="lessons">
			{#each PUZZLE_KINDS as kind (kind)}
				{@const best = endlessScore(endless, kind).best}
				<li>
					<a
						class="lesson-card"
						href="/learn/endless?kind={kind}&band={band}"
						data-sfx="on"
						data-testid="endless-card-{kind}"
					>
						<span class="lesson-title">{ENDLESS_TITLE[kind]()}</span>
						<span class="lesson-meta">
							<span>{BAND_LABEL[band]()}</span>
							{#if best > 0}
								<span class="best-pill" data-testid="endless-best-{kind}"
									>{m.learn_endlessBest({ count: best })}</span
								>
							{/if}
						</span>
					</a>
				</li>
			{/each}
		</ul>
	</section>
{/snippet}

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

	.all-solved {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: var(--space-2);
		margin: 0;
		color: var(--color-positive);

		a {
			color: var(--color-accent);
		}
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

	.track-progress {
		display: flex;
		align-items: center;
		gap: var(--space-2);
	}

	.track-bar {
		width: 5rem;
		height: 0.375rem;
		border-radius: var(--radius-pill);
		background:
			linear-gradient(var(--color-positive), var(--color-positive)) 0 / var(--fill) 100% no-repeat,
			color-mix(in srgb, var(--color-text-muted) 25%, transparent);
	}

	.track-count {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
	}

	.track-blurb {
		margin: calc(-1 * var(--space-1)) 0 0;
		color: var(--color-text-muted);
	}

	.band-heading {
		margin: var(--space-2) 0 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
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

	// the tutorial leads its track on a row of its own.
	.tutorial-item {
		grid-column: 1 / -1;
	}

	.lesson-card--tutorial,
	.lead-card {
		gap: var(--space-1);
		border-color: color-mix(in srgb, var(--color-brass) 60%, var(--color-border));
		background: color-mix(in srgb, var(--color-surface-raised) 96%, var(--color-brass));

		.lesson-title {
			font-size: var(--font-size-lg);
		}
	}

	.eyebrow {
		color: var(--color-brass);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.lesson-heading {
		display: flex;
		flex-direction: column;
	}

	.lesson-title {
		font-weight: 600;
	}

	.lesson-sub {
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
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
		align-self: flex-end;
		color: var(--color-positive);
	}

	.best-pill {
		padding: 0 var(--space-2);
		border: 1px solid color-mix(in srgb, var(--color-brass) 60%, var(--color-border));
		border-radius: var(--radius-pill);
		background: color-mix(in srgb, var(--color-brass) 18%, transparent);
		color: var(--color-text);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.band-picker {
		width: min(24rem, 100%);
	}
</style>
