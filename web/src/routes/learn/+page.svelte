<script lang="ts">
	import { untrack } from 'svelte';
	import ArrowRight from '@lucide/svelte/icons/arrow-right';
	import CircleCheck from '@lucide/svelte/icons/circle-check';
	import Play from '@lucide/svelte/icons/play';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { m } from '$lib/paraglide/messages.js';
	import { ENDLESS_TITLE, endlessScore, loadEndless, saveEndlessBand } from '$lib/learn/endless';
	import type { Band, IndexEntry } from '$lib/learn/generated/lessons';
	import { BANDS, PUZZLE_KINDS } from '$lib/learn/kinds';
	import {
		BAND_LABEL,
		FIRST_TUTORIAL,
		INDEX_TABS,
		indexHref,
		type IndexTab,
		lessonsByBand,
		lessonsByTrack,
		parseIndexTab,
		TAB_GLYPH,
		TRACK_BLURB,
		TRACK_LABEL,
		TRACKS
	} from '$lib/learn/lessons';
	import { lessonSubtitle, lessonTitle } from '$lib/learn/lesson-text';
	import { continueTab, firstUnsolved, loadProgress, solvedCount } from '$lib/learn/progress';
	import { learnSync } from '$lib/learn/learn-sync.svelte';
	import LearnUploadOffer from '$lib/learn/LearnUploadOffer.svelte';
	import type { TileCode } from '$lib/table/tile-code';
	import TileFace from '$lib/table/TileFace.svelte';
	import { isMotionReduced } from '$lib/ui/motion';
	import type { LearnEndless, LearnProgress } from '$lib/ui/settings-storage';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import BackButton from '$lib/ui/BackButton.svelte';
	import SegmentedControl from '$lib/ui/SegmentedControl.svelte';

	claimMuralVisible();

	// decorative only: the tutorial's real deal isn't in the index bundle.
	const TUTORIAL_FAN: TileCode[] = ['3m', '4m', '5m', 'z5', 'z5'];
	// a solve this recent pops its seal in when the index next renders.
	const FRESH_SOLVE_MS = 10 * 60_000;

	const groups = lessonsByTrack().map((group) => {
		const tutorials = group.lessons.filter((lesson) => lesson.lesson_kind === 'tutorial');
		const bands = lessonsByBand(group.lessons);
		const shown = [...tutorials, ...bands.flatMap((bandGroup) => bandGroup.lessons)];
		return {
			...group,
			ids: group.lessons.map((lesson) => lesson.id),
			tutorials,
			bands,
			order: new Map(shown.map((lesson, i) => [lesson.id, i]))
		};
	});

	let explicitTab = $derived(parseIndexTab(page.url.searchParams.get('track')));
	let tab = $derived(explicitTab ?? TRACKS[0]);
	let selectedGroup = $derived(groups.find((group) => group.track === tab));
	let nextTab = $derived(INDEX_TABS[INDEX_TABS.indexOf(tab) + 1] ?? null);

	// read after mount so the SSR'd index and its hydration agree (all unsolved), and again once
	// a signed-in account's progress arrives
	let progress = $state<LearnProgress>({});
	let endless = $state<LearnEndless>({ band: 'beginner', scores: {} });
	$effect(() => {
		void learnSync.version;
		progress = loadProgress();
		endless = loadEndless();
		// no ?track=: open on where the player left off, without a history entry
		untrack(() => {
			if (explicitTab) return;
			const target = continueTab(progress);
			if (target !== tab) {
				void goto(indexHref(target), { replaceState: true, noScroll: true, keepFocus: true });
			}
		});
	});
	let band = $derived(endless.band);

	let tabBar = $state<HTMLElement>();
	// instant on load, smooth only for a tab change
	let tabBarScrolled = false;
	$effect(() => {
		const current = tabBar?.querySelector(`[data-tab="${tab}"]`);
		if (!tabBar || !current) return;
		current.scrollIntoView({
			inline: 'nearest',
			block: 'nearest',
			behavior: tabBarScrolled && !isMotionReduced() ? 'smooth' : 'auto'
		});
		tabBarScrolled = true;
		// font swap and post-mount counts widen tabs after the first scroll
		const widths = new Map<Element, number>();
		for (const el of tabBar.children) widths.set(el, el.getBoundingClientRect().width);
		const observer = new ResizeObserver((entries) => {
			const changed = entries.some(
				(entry) => entry.borderBoxSize[0].inlineSize !== widths.get(entry.target)
			);
			for (const entry of entries) widths.set(entry.target, entry.borderBoxSize[0].inlineSize);
			if (changed) current.scrollIntoView({ inline: 'nearest', block: 'nearest' });
		});
		for (const el of tabBar.children) observer.observe(el, { box: 'border-box' });
		return () => observer.disconnect();
	});
	// the tutorial leads until it's solved; after that, the first unsolved lesson does.
	let next = $derived(firstUnsolved(progress));
	let tutorialSolved = $derived(progress[FIRST_TUTORIAL.id]?.solved ?? false);

	function tabLabel(value: IndexTab): string {
		return value === 'endless' ? m.learn_tabEndless() : TRACK_LABEL[value]();
	}

	function freshlySolved(id: string): boolean {
		const solvedAt = progress[id]?.solvedAt;
		return solvedAt !== undefined && Date.now() - solvedAt < FRESH_SOLVE_MS;
	}

	function pickBand(value: Band): void {
		endless = { ...endless, band: value };
		saveEndlessBand(value);
	}
</script>

<svelte:head>
	<title>{m.learn_pageTitle()}</title>
</svelte:head>

<div class="learn-page" data-hue={tab}>
	<header class="page-header">
		<BackButton label={m.learn_backLabel()} href="/" />
		<h1>{m.learn_title()}</h1>
	</header>
	<p class="subtitle">{m.learn_subtitle()}</p>

	<LearnUploadOffer />

	{#if tutorialSolved && next}
		{@const subtitle = lessonSubtitle(next)}
		<a
			class="lesson-card lead-card"
			href="/learn/{next.id}"
			data-hue={next.track}
			data-sfx="on"
			data-testid="learn-continue"
		>
			<span class="glyph-tile" aria-hidden="true">{TAB_GLYPH[next.track]()}</span>
			<span class="lesson-heading">
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
			</span>
			<span class="go-chip" aria-hidden="true"><ArrowRight size={18} /></span>
		</a>
	{:else if tutorialSolved}
		<p class="all-solved" data-testid="learn-all-solved">
			<CircleCheck size={18} aria-hidden="true" />
			<span>{m.learn_allSolved()}</span>
			<a
				href={indexHref('endless')}
				data-sveltekit-replacestate
				data-sveltekit-noscroll
				data-sveltekit-keepfocus>{m.learn_allSolvedEndless()}</a
			>
		</p>
	{/if}

	<nav class="tabs" aria-label={m.learn_tabsAriaLabel()} bind:this={tabBar}>
		{#each groups as group (group.track)}
			{@const solved = solvedCount(progress, group.ids)}
			{@render tabLink(group.track, {
				solved,
				total: group.ids.length
			})}
		{/each}
		{@render tabLink('endless', null)}
	</nav>

	{#if selectedGroup}
		{@const group = selectedGroup}
		{@const ids = group.ids}
		{@const solved = solvedCount(progress, ids)}
		<section class="track" aria-labelledby="track-{group.track}" data-testid="track-{group.track}">
			<header class="track-header">
				<span class="glyph-tile glyph-tile--lg" aria-hidden="true">{TAB_GLYPH[group.track]()}</span>
				<span class="track-heading">
					<h2 id="track-{group.track}">{TRACK_LABEL[group.track]()}</h2>
					<p class="track-blurb">{TRACK_BLURB[group.track]()}</p>
				</span>
				<span class="track-progress">
					<span
						class="track-ring"
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
			{#if group.tutorials.length > 0}
				<ul class="lessons">
					{#each group.tutorials as lesson (lesson.id)}
						<li class="tutorial-item" style:--i={group.order.get(lesson.id)}>
							{@render card(lesson, false)}
						</li>
					{/each}
				</ul>
			{/if}
			{#each group.bands as bandGroup (bandGroup.band)}
				{@const level = BANDS.indexOf(bandGroup.band)}
				<h3 class="band-heading" data-testid="band-{group.track}-{bandGroup.band}">
					<span class="pips" aria-hidden="true">
						{#each BANDS as pip, i (pip)}
							<span class="pip" class:pip--on={i <= level}></span>
						{/each}
					</span>
					{BAND_LABEL[bandGroup.band]()}
				</h3>
				<ul class="lessons">
					{#each bandGroup.lessons as lesson (lesson.id)}
						<li style:--i={group.order.get(lesson.id)}>
							{@render card(lesson, bandGroup.numbered.has(lesson.id))}
						</li>
					{/each}
				</ul>
			{/each}
		</section>
	{:else}
		{@render endlessSection()}
	{/if}

	{#if nextTab}
		<a
			class="next-track"
			href={indexHref(nextTab)}
			data-hue={nextTab}
			data-sveltekit-replacestate
			data-testid="learn-next-track"
		>
			<span class="glyph-tile" aria-hidden="true">{TAB_GLYPH[nextTab]()}</span>
			<span class="next-track-label">{m.learn_nextTrack({ track: tabLabel(nextTab) })}</span>
			<ArrowRight size={18} aria-hidden="true" />
		</a>
	{/if}
</div>

{#snippet tabLink(value: IndexTab, count: { solved: number; total: number } | null)}
	{@const current = value === tab}
	<a
		class="tab"
		class:tab--current={current}
		href={indexHref(value)}
		aria-current={current ? 'page' : undefined}
		data-hue={value}
		data-sveltekit-replacestate
		data-sveltekit-noscroll
		data-sveltekit-keepfocus
		data-tab={value}
		data-testid="learn-tab-{value}"
	>
		<span class="tab-glyph" aria-hidden="true">{TAB_GLYPH[value]()}</span>
		<span>{tabLabel(value)}</span>
		{#if count}
			<span class="tab-count" data-testid="learn-tab-count-{value}" aria-hidden="true"
				>{m.learn_solvedCount(count)}</span
			>
			<span class="sr-only">{m.learn_solvedCountAriaLabel(count)}</span>
		{/if}
	</a>
{/snippet}

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
		<span class="lesson-heading">
			{#if tutorial}
				<span class="eyebrow">{done ? m.learn_tutorialLabel() : m.learn_tutorialStartHere()}</span>
			{/if}
			<span class="lesson-title">{lessonTitle(lesson)}</span>
			{#if subtitle}
				<span class="lesson-sub" data-testid="lesson-sub-{lesson.id}">{subtitle}</span>
			{/if}
			{#if tutorial && !done}
				<span class="play-chip" aria-hidden="true">
					<Play size={14} />{m.learn_tutorialPlay()}
				</span>
			{/if}
		</span>
		{#if tutorial}
			<span class="fan" aria-hidden="true">
				{#each TUTORIAL_FAN as code, i (i)}
					<span class="fan-tile" style:--k={i - (TUTORIAL_FAN.length - 1) / 2}>
						<TileFace {code} />
					</span>
				{/each}
			</span>
		{/if}
		{#if done}
			<span
				class="solved-seal"
				class:solved-seal--fresh={freshlySolved(lesson.id)}
				title={m.learn_solvedMark()}
			>
				<span aria-hidden="true">{m.learn_solvedSeal()}</span>
				<span class="sr-only">{m.learn_solvedMark()}</span>
			</span>
		{/if}
	</a>
{/snippet}

{#snippet endlessSection()}
	<section id="endless" class="track endless" aria-labelledby="endless-title" data-testid="endless">
		<header class="track-header">
			<span class="glyph-tile glyph-tile--lg" aria-hidden="true">{TAB_GLYPH.endless()}</span>
			<span class="track-heading">
				<h2 id="endless-title">{m.learn_endlessHeading()}</h2>
				<p class="track-blurb">{m.learn_endlessIntro()}</p>
			</span>
		</header>
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
			{#each PUZZLE_KINDS as kind, i (kind)}
				{@const best = endlessScore(endless, kind).best}
				<li style:--i={i}>
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
	@use 'sass:map';
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	// one hue per index tab, all light enough for --color-tile-ink on top. none is --color-accent:
	// that red stays the urgent signal.
	$track-hues: (
		basics: #e6d3a8,
		waits: #6cc3a0,
		efficiency: #7aaed6,
		defence: #a993d6,
		faan: #d6ae5c,
		endless: #e08fb4
	);

	// registered as a colour so the scrim's gradient can transition between tracks.
	@property --track-hue {
		syntax: '<color>';
		inherits: true;
		initial-value: #{map.get($track-hues, basics)};
	}

	@each $track, $hue in $track-hues {
		[data-hue='#{$track}'] {
			--track-hue: #{$hue};
		}
	}

	.learn-page {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		flex-direction: column;
		gap: var(--space-5);
		width: min(60rem, 100%);
		min-height: 100dvh;
		margin: 0 auto;
		padding: var(--space-5);

		// scrim over the mural: the tiles behind stay texture, not content.
		&::before {
			content: '';
			position: fixed;
			inset: 0;
			z-index: -1;
			background:
				radial-gradient(
					ellipse 70rem 40rem at 50% 0%,
					color-mix(in srgb, var(--track-hue) 10%, transparent),
					transparent 70%
				),
				radial-gradient(ellipse at 50% 30%, rgb(28 20 16 / 0.45), rgb(28 20 16 / 0.8) 75%);
			pointer-events: none;

			@include a11y.motion-ok {
				transition: --track-hue var(--dur-4) var(--ease-out);
			}
		}

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

	// ivory tile with a carved glyph, as the lobby's action cards; ink tinted by the track.
	.glyph-tile {
		flex: none;
		display: grid;
		place-items: center;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: var(--radius-sm);
		background: var(--color-tile);
		color: color-mix(in srgb, var(--track-hue) 45%, var(--color-tile-ink));
		font-size: var(--font-size-base);
		font-weight: 700;
		line-height: 1;
		box-shadow:
			0 2px 0 var(--color-tile-edge),
			0 4px 0 var(--color-tile-side);
	}

	.glyph-tile--lg {
		width: 3rem;
		height: 3rem;
		font-size: var(--font-size-lg);
	}

	// padding: room for the focus ring inside the scroller's clip.
	// relative: keeps the absolute sr-only counts inside that clip, or they widen the page.
	.tabs {
		position: relative;
		display: flex;
		gap: 2px;
		min-width: 0;
		padding: var(--space-1);
		overflow-x: auto;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		scroll-snap-type: x proximity;
		scrollbar-width: thin;
	}

	.tab {
		display: flex;
		flex: 1 0 auto;
		align-items: center;
		justify-content: center;
		gap: var(--space-2);
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		border-radius: calc(var(--radius-md) - 3px);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-weight: 600;
		white-space: nowrap;
		text-decoration: none;
		scroll-snap-align: start;

		@include a11y.motion-ok {
			transition:
				background-color var(--dur-control) ease,
				color var(--dur-control) ease;
		}

		&:hover:not(.tab--current) {
			background: color-mix(in srgb, var(--track-hue) 10%, transparent);
			color: var(--color-text);
		}
	}

	.tab-glyph {
		color: var(--track-hue);
		font-weight: 700;
	}

	.tab--current {
		background: var(--track-hue);
		color: var(--color-tile-ink);
		font-weight: 700;

		.tab-glyph {
			color: inherit;
		}
	}

	.tab-count {
		font-size: var(--font-size-xs);
		font-variant-numeric: tabular-nums;
	}

	.track {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}

	.track-header {
		display: flex;
		align-items: center;
		gap: var(--space-3) var(--space-4);
		padding-bottom: var(--space-3);
		border-bottom: 1px solid color-mix(in srgb, var(--track-hue) 35%, var(--color-border));

		h2 {
			margin: 0;
			font-size: var(--font-size-lg);
		}
	}

	.track-heading {
		display: flex;
		flex: 1;
		flex-direction: column;
		gap: var(--space-1);
		min-width: 0;
	}

	.track-progress {
		display: flex;
		flex: none;
		align-items: center;
		gap: var(--space-2);
	}

	// a conic fill masked to a ring.
	.track-ring {
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 50%;
		background: conic-gradient(
			var(--track-hue) var(--fill),
			color-mix(in srgb, var(--color-text-muted) 25%, transparent) 0
		);
		mask: radial-gradient(farthest-side, transparent calc(100% - 5px), #000 calc(100% - 4px));
	}

	.track-count {
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
	}

	.track-blurb {
		margin: 0;
		color: var(--color-text-muted);
	}

	.band-heading {
		display: flex;
		align-items: center;
		gap: var(--space-2);
		margin: var(--space-2) 0 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.pips {
		display: inline-flex;
		gap: 3px;
	}

	.pip {
		width: 0.5rem;
		height: 0.5rem;
		border: 1.5px solid var(--track-hue);
		border-radius: 50%;
	}

	.pip--on {
		background: var(--track-hue);
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

		li {
			@include a11y.motion-ok {
				animation: card-in var(--dur-3) var(--ease-out) backwards;
				animation-delay: calc(var(--i, 0) * 30ms);
			}
		}
	}

	.lesson-card {
		position: relative;
		display: flex;
		flex-direction: column;
		justify-content: space-between;
		gap: var(--space-2);
		height: 100%;
		padding: var(--space-3) var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);
		box-shadow: inset 0 1px 0 rgb(255 255 255 / 0.05);
		color: var(--color-text);
		text-decoration: none;
		transition:
			border-color var(--dur-control) ease,
			box-shadow var(--dur-1) var(--ease-out),
			translate var(--dur-1) var(--ease-out);

		&:hover {
			border-color: color-mix(in srgb, var(--track-hue) 55%, var(--color-border));
			box-shadow:
				inset 0 1px 0 rgb(255 255 255 / 0.05),
				0 10px 22px -10px rgb(10 4 2 / 0.8);
		}

		@include a11y.motion-ok {
			&:hover {
				translate: 0 -2px;
			}
		}
	}

	.lesson-card--solved {
		padding-right: calc(var(--space-4) + 2rem);
		border-color: color-mix(in srgb, var(--track-hue) 40%, var(--color-border));
		background: color-mix(
			in srgb,
			color-mix(in srgb, var(--color-surface-raised) 92%, var(--track-hue)) 92%,
			transparent
		);
	}

	// the tutorial leads its track on a row of its own.
	.tutorial-item {
		grid-column: 1 / -1;
	}

	.lesson-card--tutorial,
	.lead-card {
		flex-direction: row;
		align-items: center;
		justify-content: flex-start;
		gap: var(--space-4);
		border-color: color-mix(in srgb, var(--track-hue) 60%, var(--color-border));
		background:
			linear-gradient(
				100deg,
				color-mix(in srgb, var(--track-hue) 16%, transparent),
				transparent 60%
			),
			color-mix(in srgb, var(--color-surface-raised) 96%, transparent);

		.lesson-heading {
			flex: 1;
		}

		.lesson-title {
			font-size: var(--font-size-lg);
		}
	}

	.lesson-card--tutorial {
		padding: var(--space-4) var(--space-5);

		@include layout.phone-only {
			padding: var(--space-4);
		}
	}

	.eyebrow {
		color: var(--track-hue);
		font-size: var(--font-size-xs);
		font-weight: 700;
		letter-spacing: 0.1em;
		text-transform: uppercase;
	}

	.lesson-heading {
		display: flex;
		flex-direction: column;
		gap: 2px;
		min-width: 0;
	}

	.lesson-title {
		font-weight: 600;
	}

	.lesson-sub {
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
	}

	.play-chip,
	.go-chip {
		display: inline-flex;
		align-items: center;
		background: var(--track-hue);
		color: var(--color-tile-ink);
	}

	.play-chip {
		align-self: flex-start;
		gap: var(--space-1);
		margin-top: var(--space-2);
		padding: var(--space-1) var(--space-3);
		border-radius: var(--radius-pill);
		font-size: var(--font-size-sm);
		font-weight: 700;
	}

	.go-chip {
		flex: none;
		justify-content: center;
		width: 2.25rem;
		height: 2.25rem;
		border-radius: 50%;
	}

	// a loose hand fanned from its middle tile; it spreads further on hover.
	.fan {
		display: flex;
		flex: none;
		height: 3.5rem;
		padding: 0 var(--space-3) var(--space-2) 0;

		@include layout.phone-only {
			height: 2.5rem;
			padding-right: var(--space-1);
		}
	}

	.fan-tile {
		height: 100%;
		margin-left: -0.6rem;
		rotate: calc(var(--k) * 6deg);
		translate: 0 calc(var(--k) * var(--k) * 2px);
		transform-origin: 50% 120%;

		&:first-child {
			margin-left: 0;
		}

		@include a11y.motion-ok {
			transition:
				rotate var(--dur-2) var(--ease-out),
				translate var(--dur-2) var(--ease-out);
		}
	}

	.lesson-card:hover .fan-tile {
		@include a11y.motion-ok {
			rotate: calc(var(--k) * 9deg);
			translate: 0 calc(var(--k) * var(--k) * 3px - 3px);
		}
	}

	.lesson-meta {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-2);
		color: var(--color-text-muted);
		font-size: var(--font-size-xs);
	}

	// a carved seal pressed on the corner, in the track's hue (the cinnabar seal is the win signal).
	.solved-seal {
		position: absolute;
		top: var(--space-2);
		right: var(--space-2);
		display: grid;
		place-items: center;
		width: 1.75rem;
		height: 1.75rem;
		border: 3px double var(--track-hue);
		border-radius: var(--radius-sm);
		color: var(--track-hue);
		font-size: var(--font-size-sm);
		font-weight: 700;
		line-height: 1;
		rotate: -8deg;
	}

	.solved-seal--fresh {
		@include a11y.motion-ok {
			animation: seal-press var(--dur-4) var(--ease-place) backwards;
			animation-delay: calc(var(--i, 0) * 30ms + var(--dur-3));
		}
	}

	.lesson-card--tutorial .solved-seal {
		position: static;
		order: -1;
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

	.next-track {
		display: flex;
		align-items: center;
		gap: var(--space-3);
		margin-top: var(--space-2);
		padding: var(--space-3) var(--space-4);
		border: 1px dashed color-mix(in srgb, var(--track-hue) 50%, var(--color-border));
		border-radius: var(--radius-md);
		color: var(--color-text);
		font-weight: 600;
		text-decoration: none;
		transition: background-color var(--dur-control) ease;

		&:hover {
			background: color-mix(in srgb, var(--track-hue) 10%, transparent);
		}

		:global(svg) {
			margin-left: auto;
			color: var(--track-hue);
		}
	}

	@keyframes card-in {
		from {
			opacity: 0;
			translate: 0 8px;
		}
	}

	@keyframes seal-press {
		0% {
			opacity: 0;
			scale: 1.8;
			rotate: -20deg;
		}
		60% {
			opacity: 1;
			scale: 0.92;
			rotate: -6deg;
		}
		100% {
			scale: 1;
			rotate: -8deg;
		}
	}
</style>
