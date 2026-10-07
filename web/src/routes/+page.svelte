<script lang="ts">
	import { goto } from '$app/navigation';
	import { getLocale, setLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import CreateTableDialog from '$lib/ui/CreateTableDialog.svelte';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';
	import PracticeSetupDialog from '$lib/ui/PracticeSetupDialog.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';

	claimMuralVisible();

	// opens a dialog to pick the ruleset rather than navigating straight there -- RuleSet is
	// fixed at table construction with no path to change it after.
	let showCreateDialog = $state(false);

	function handleCreated(tableId: string): void {
		showCreateDialog = false;
		goto(`/table/${tableId}`);
	}

	// practice mode: a solo table with seats 1-3 bot-bound at creation. Opens a difficulty-picker
	// dialog first since bot tier is fixed at construction; `?practice=1` here is unrelated in spelling to the wire's `&practice=true`.
	let showPracticeDialog = $state(false);

	let showGuide = $state(false);

	function handlePracticeCreated(tableId: string): void {
		showPracticeDialog = false;
		goto(`/table/${tableId}?practice=1`);
	}
</script>

<div class="lobby">
	<div class="lobby-inner">
		<header class="brand">
			<span class="seal" aria-hidden="true"
				>{#each [...m.lobby_sealMark()] as char}<span class="seal-char">{char}</span>{/each}</span
			>
			<div class="brand-text">
				<h1 class="title">{m.lobby_title()}</h1>
			</div>
		</header>

		<!-- the button is the card's accessible name; its ::after stretches the hit area over
		the whole card so the description stays outside the name. -->
		<ul class="actions">
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_createTableGlyph()}</span>
				<button
					type="button"
					class="action-title"
					data-testid="lobby-create-table"
					aria-describedby="lobby-create-desc"
					onclick={() => (showCreateDialog = true)}>{m.lobby_createTableButton()}</button
				>
				<p id="lobby-create-desc" class="action-desc">{m.lobby_createTableDesc()}</p>
			</li>
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_practiceGlyph()}</span>
				<button
					type="button"
					class="action-title"
					data-testid="lobby-practice-bots"
					aria-describedby="lobby-practice-desc"
					onclick={() => (showPracticeDialog = true)}>{m.lobby_practiceButton()}</button
				>
				<p id="lobby-practice-desc" class="action-desc">{m.lobby_practiceDesc()}</p>
			</li>
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_guideGlyph()}</span>
				<button
					type="button"
					class="action-title"
					data-testid="lobby-guide"
					aria-describedby="lobby-guide-desc"
					onclick={() => (showGuide = true)}>{m.lobby_guideButton()}</button
				>
				<p id="lobby-guide-desc" class="action-desc">{m.lobby_guideDesc()}</p>
			</li>
		</ul>

		<nav class="quiet-links">
			<span>
				{m.lobby_joinGamePrompt()}
				<a class="quiet-link" data-testid="lobby-join-game-link" href="/tables"
					>{m.lobby_joinGameLink()}</a
				>
			</span>
			<button
				type="button"
				class="quiet-link"
				data-testid="lobby-language"
				onclick={() => setLocale(getLocale() === 'en' ? 'zh-Hant' : 'en')}
			>
				{m.lobby_languageButton()}
			</button>
		</nav>
	</div>
</div>

{#if showGuide}
	<GuideDialog onClose={() => (showGuide = false)} />
{/if}

{#if showCreateDialog}
	<CreateTableDialog onCreated={handleCreated} onCancel={() => (showCreateDialog = false)} />
{/if}

{#if showPracticeDialog}
	<PracticeSetupDialog
		onCreated={handlePracticeCreated}
		onCancel={() => (showPracticeDialog = false)}
	/>
{/if}

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/layout';

	.lobby {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100dvh;
		padding: var(--space-8) var(--space-5);

		@include layout.phone-only {
			padding: var(--space-6) var(--space-4);
		}
	}

	.lobby-inner {
		display: flex;
		flex-direction: column;
		gap: var(--space-6);
		width: min(56rem, 100%);
	}

	.brand {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-5);

		@include layout.phone-only {
			gap: var(--space-4);
		}
	}

	// carved-seal mark: vertical CJK in an ink-red stamp, slightly rotated like a hand press.
	// stacked chars, not writing-mode: vertical-rl -- vertical mode positions upright glyphs via the font's vertical origin metrics, which browsers synthesise per-font (off-centre column, extra left gap, on some devices).
	.seal {
		flex: none;
		display: grid;
		place-items: center;
		gap: 0.08em;
		padding: var(--space-2) var(--space-1);
		border: 3px double var(--color-text);
		border-radius: var(--radius-sm);
		background: var(--color-accent);
		color: var(--color-text);
		font-size: calc(var(--font-size-display) * 0.42);
		font-weight: 700;
		line-height: 1.05;
		box-shadow: 0 6px 18px -4px rgb(10 4 2 / 0.7);
		transform: rotate(-4deg);
	}

	.title {
		margin: 0;
		font-size: var(--font-size-display);
		font-weight: 800;
		letter-spacing: -0.03em;
		line-height: 1;
		text-shadow: 0 2px 12px rgb(0 0 0 / 0.6);
	}

	.actions {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: var(--space-4);
		margin: 0;
		padding: 0;
		list-style: none;

		@include layout.phone-only {
			grid-template-columns: 1fr;
			gap: var(--space-3);
		}
	}

	.action-card {
		position: relative;
		display: grid;
		grid-template-columns: auto 1fr;
		grid-template-areas:
			'glyph title'
			'glyph desc';
		column-gap: var(--space-3);
		row-gap: var(--space-1);
		align-content: start;
		padding: var(--space-4);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: color-mix(in srgb, var(--color-surface-raised) 92%, transparent);
		box-shadow:
			inset 0 1px 0 rgb(255 255 255 / 0.06),
			0 10px 24px -8px rgb(10 4 2 / 0.7);
		transition:
			transform var(--dur-1) var(--ease-out),
			border-color var(--dur-1) var(--ease-out);

		&:hover {
			border-color: color-mix(in srgb, var(--color-brass) 55%, var(--color-border) 45%);
		}

		&:has(.action-title:focus-visible) {
			@include a11y.focus-ring;
		}

		@include a11y.motion-ok {
			&:hover {
				transform: translateY(-2px);
			}
		}
	}

	.action-glyph {
		grid-area: glyph;
		display: grid;
		place-items: center;
		width: 2.75rem;
		height: 2.75rem;
		border-radius: var(--radius-sm);
		background: var(--color-tile);
		color: var(--color-tile-ink);
		font-size: var(--font-size-lg);
		font-weight: 700;
		box-shadow:
			0 2px 0 var(--color-tile-edge),
			0 4px 0 var(--color-tile-side);
	}

	.action-title {
		grid-area: title;
		justify-self: start;
		padding: 0;
		border: none;
		background: none;
		color: var(--color-text);
		font: inherit;
		font-size: var(--font-size-lg);
		font-weight: 700;
		line-height: 1.2;
		text-align: start;
		cursor: pointer;

		// stretched hit area: the whole card is one tap target, at least --tap-target-min tall.
		&::after {
			content: '';
			position: absolute;
			inset: 0;
			border-radius: inherit;
		}

		&:focus-visible {
			outline: none;
		}
	}

	.action-desc {
		grid-area: desc;
		margin: 0;
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		line-height: 1.4;
	}

	.quiet-links {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: var(--space-2) var(--space-5);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
	}

	.quiet-link {
		display: inline-flex;
		align-items: center;
		min-height: var(--tap-target-min);
		padding: 0 var(--space-1);
		border: none;
		background: none;
		color: var(--color-text);
		font: inherit;
		text-decoration: underline;
		text-decoration-color: color-mix(in srgb, var(--color-brass) 60%, transparent);
		text-underline-offset: 0.2em;
		cursor: pointer;

		&:hover {
			color: var(--color-brass);
		}
	}
</style>
