<script lang="ts">
	import { onMount } from 'svelte';
	import {
		ENDLESS_TITLE,
		EMPTY_SCORE,
		endlessScore,
		fetchRandomLesson,
		recordEndlessAnswer,
		recordEndlessSkip,
		rememberRecent,
		saveEndlessScore,
		type EndlessFetch
	} from '$lib/learn/endless';
	import type { Lesson } from '$lib/learn/generated/lessons';
	import { BAND_LABEL } from '$lib/learn/lessons';
	import type { GradeResult } from '$lib/learn/types';
	import { m } from '$lib/paraglide/messages.js';
	import BackButton from '$lib/ui/BackButton.svelte';
	import { loadLearnEndless } from '$lib/ui/settings-storage';
	import Spinner from '$lib/ui/Spinner.svelte';
	import PuzzlePage from '../_components/PuzzlePage.svelte';
	import type { PageProps } from './$types';

	let { data }: PageProps = $props();
	let kind = $derived(data.kind);
	let band = $derived(data.band);

	let lesson = $state<Lesson | null>(null);
	let failure = $state<Exclude<EndlessFetch, { ok: true }> | null>(null);
	let loading = $state(true);
	let recent: string[] = [];
	let score = $state(EMPTY_SCORE);
	let missed = $state(false);
	let solved = $state(false);

	async function load(): Promise<void> {
		loading = true;
		failure = null;
		const fetched = await fetchRandomLesson({ kind, band, exclude: recent });
		loading = false;
		if (!fetched.ok) {
			failure = fetched;
			return;
		}
		recent = rememberRecent(recent, fetched.lesson.id);
		missed = false;
		solved = false;
		lesson = fetched.lesson;
	}

	function graded(result: GradeResult): void {
		const wasMissed = missed;
		if (result !== 'correct') missed = true;
		else solved = true;
		score = saveEndlessScore(kind, (s) => recordEndlessAnswer(s, result, wasMissed));
	}

	function next(): void {
		if (!solved) score = saveEndlessScore(kind, recordEndlessSkip);
		void load();
	}

	onMount(() => {
		score = endlessScore(loadLearnEndless(), kind);
		void load();
	});

	let title = $derived(ENDLESS_TITLE[kind]());
	// PuzzlePage sets the page title itself
	let showing = $derived(lesson !== null && !loading && failure === null);
</script>

{#snippet scoreLine()}
	<span class="score" data-testid="endless-score">
		<span data-testid="endless-streak" data-streak={score.streak}
			>{m.learn_endlessStreak({ count: score.streak })}</span
		>
		<span class="best">{m.learn_endlessBest({ count: score.best })}</span>
	</span>
{/snippet}

{#snippet navExtra()}
	{@render scoreLine()}
	{#if !solved}
		<button type="button" class="skip" data-sfx="on" data-testid="endless-skip" onclick={next}
			>{m.learn_endlessSkip()}</button
		>
	{/if}
{/snippet}

{#snippet afterCorrect()}
	<button type="button" class="next-button" data-sfx="on" data-testid="endless-next" onclick={next}
		>{m.learn_endlessNext()}</button
	>
{/snippet}

<svelte:head>
	{#if !showing}
		<title>{m.learn_lessonPageTitle({ title })}</title>
	{/if}
</svelte:head>

{#if lesson && showing}
	<PuzzlePage {lesson} {navExtra} {afterCorrect} onGraded={graded} />
{:else}
	<div class="endless-status">
		<BackButton label={m.learn_indexLabel()} href="/learn" />
		<section class="status-card" aria-live="polite">
			<p class="meta">{BAND_LABEL[band]()}</p>
			<h1>{title}</h1>
			{#if failure}
				<p class="error" role="alert" data-testid="endless-error" data-error={failure.error}>
					{#if failure.error === 'rate_limited'}
						{failure.retryAfterS === null
							? m.learn_endlessRateLimited()
							: m.learn_endlessRateLimitedFor({ seconds: failure.retryAfterS })}
					{:else}
						{m.learn_endlessUnavailable()}
					{/if}
				</p>
				<button
					type="button"
					class="next-button"
					data-sfx="on"
					data-testid="endless-retry"
					onclick={() => void load()}>{m.learn_endlessRetry()}</button
				>
			{:else}
				<div class="loading" data-testid="endless-loading">
					<Spinner />
					<span>{m.learn_endlessLoading()}</span>
				</div>
			{/if}
			{@render scoreLine()}
		</section>
	</div>
{/if}

<style lang="scss">
	@use '$lib/styles/buttons';

	.score {
		display: inline-flex;
		align-items: center;
		gap: var(--space-3);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
	}

	.skip {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-ghost;
	}

	.next-button {
		@include buttons.btn-base(var(--space-5));
		@include buttons.btn-primary;
		align-self: flex-start;
	}

	.endless-status {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		flex-direction: column;
		gap: var(--space-4);
		width: min(32rem, 100%);
		margin: 0 auto;
		padding: var(--space-5) var(--space-4);
	}

	.status-card {
		@include buttons.panel-elevated;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		padding: var(--space-4);
		background: var(--color-surface);

		h1 {
			margin: 0;
			font-size: var(--font-size-xl);
		}
	}

	.meta {
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.loading {
		display: flex;
		align-items: center;
		gap: var(--space-3);
	}

	.error {
		margin: 0;
		color: var(--color-negative);
	}
</style>
