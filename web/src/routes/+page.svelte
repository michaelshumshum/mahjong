<script lang="ts">
	import { goto } from '$app/navigation';
	import { getLocale, setLocale } from '$lib/paraglide/runtime.js';
	import { m } from '$lib/paraglide/messages.js';
	import GuideDialog from '$lib/ui/GuideDialog.svelte';
	import PracticeSetupDialog from '$lib/ui/PracticeSetupDialog.svelte';
	import { claimMuralVisible } from '$lib/ui/mural-visibility.svelte';
	import Languages from '@lucide/svelte/icons/languages';
	import SettingsIcon from '@lucide/svelte/icons/settings';
	import DismissablePanel from '$lib/ui/DismissablePanel.svelte';
	import Settings from '$lib/ui/Settings.svelte';
	import type { AutoArm, ClientPrefs } from '$lib/ui/client-prefs';
	import { applyClientPrefs } from '$lib/ui/apply-client-prefs';
	import {
		DEFAULT_AUTO_ARM,
		DEFAULT_CLIENT_PREFS,
		loadAutoArm,
		loadClientPrefs,
		saveAutoArm,
		saveClientPrefs
	} from '$lib/ui/settings-storage';

	claimMuralVisible();

	const ICON = { size: 18, strokeWidth: 1.8 };
	const otherLocale = getLocale() === 'en' ? 'zh-Hant' : 'en';

	// practice mode: a solo table with seats 1-3 bot-bound at creation. Opens a difficulty-picker
	// dialog first since bot tier is fixed at construction; `?practice=1` only tags the table page.
	let showPracticeDialog = $state(false);

	let showGuide = $state(false);

	// read on open, not at init: the lobby is server-rendered, where storage is unavailable.
	// autoArm only persists here; the table page re-sends it on its next connection.
	let showSettings = $state(false);
	let autoArm: AutoArm = $state({ ...DEFAULT_AUTO_ARM });
	let clientPrefs: ClientPrefs = $state({ ...DEFAULT_CLIENT_PREFS });

	function openSettings(): void {
		autoArm = loadAutoArm() ?? { ...DEFAULT_AUTO_ARM };
		clientPrefs = loadClientPrefs() ?? { ...DEFAULT_CLIENT_PREFS };
		showSettings = true;
	}

	function handlePracticeCreated(tableId: string): void {
		showPracticeDialog = false;
		goto(`/table/${tableId}?practice=1`);
	}
</script>

<svelte:head>
	<title>{m.lobby_title()}</title>
</svelte:head>

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

		<!-- the button's ::after stretches the hit area over the whole card. -->
		<ul class="actions">
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_playOnlineGlyph()}</span>
				<a class="action-title" data-testid="lobby-play-online" data-sfx="on" href="/tables"
					>{m.lobby_playOnlineButton()}</a
				>
			</li>
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_practiceGlyph()}</span>
				<button
					type="button"
					class="action-title"
					data-testid="lobby-practice-bots"
					onclick={() => (showPracticeDialog = true)}>{m.lobby_practiceButton()}</button
				>
			</li>
			<li class="action-card">
				<span class="action-glyph" aria-hidden="true">{m.lobby_guideGlyph()}</span>
				<button
					type="button"
					class="action-title"
					data-testid="lobby-guide"
					onclick={() => (showGuide = true)}>{m.lobby_guideButton()}</button
				>
			</li>
		</ul>

		<div class="utility-bar">
			<!-- shorthand label, full target-language name as the accessible name -->
			<button
				type="button"
				class="utility-btn"
				data-testid="lobby-language"
				lang={otherLocale}
				aria-label={m.lobby_languageButton()}
				onclick={() => setLocale(otherLocale)}
			>
				<Languages {...ICON} />
				<span>{m.lobby_languageShort()}</span>
			</button>
			<button
				type="button"
				class="utility-btn"
				data-testid="lobby-settings"
				aria-haspopup="dialog"
				onclick={openSettings}
			>
				<SettingsIcon {...ICON} />
				<span>{m.settings_title()}</span>
			</button>
		</div>
	</div>

	<a
		class="source-link"
		data-testid="lobby-source-link"
		href="https://github.com/michaelshumshum/mahjong"
		target="_blank"
		rel="noopener noreferrer"
	>
		<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" fill="currentColor"
			><path
				d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"
			/></svg
		>
		{m.lobby_sourceLink()}
	</a>
</div>

{#if showGuide}
	<GuideDialog onClose={() => (showGuide = false)} />
{/if}

{#if showSettings}
	<DismissablePanel onClose={() => (showSettings = false)} label={m.settings_title()}>
		<Settings
			{autoArm}
			prefs={clientPrefs}
			onAutoArmChange={(next) => {
				autoArm = next;
				saveAutoArm(next);
			}}
			onPrefsChange={(next) => {
				clientPrefs = next;
				saveClientPrefs(next);
				applyClientPrefs(next);
			}}
		/>
	</DismissablePanel>
{/if}

{#if showPracticeDialog}
	<PracticeSetupDialog
		onCreated={handlePracticeCreated}
		onCancel={() => (showPracticeDialog = false)}
	/>
{/if}

<style lang="scss">
	@use '$lib/styles/a11y';
	@use '$lib/styles/buttons';
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
			// clears the absolutely-positioned source link when the stacked cards fill the screen.
			padding-bottom: calc(var(--space-6) + var(--tap-target-min));
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
		grid-template-areas: 'glyph title';
		column-gap: var(--space-3);
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
		align-self: center;
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
		text-decoration: none;
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

	.utility-bar {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		justify-content: center;
		gap: var(--space-3);
	}

	.utility-btn {
		@include buttons.btn-base(var(--space-3));
		@include buttons.btn-secondary;
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		font-size: var(--font-size-sm);

		:global(svg) {
			flex-shrink: 0;
			color: var(--color-brass);
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}

	.source-link {
		position: absolute;
		right: var(--space-8);
		bottom: var(--space-3);
		display: inline-flex;
		align-items: center;
		gap: var(--space-2);
		min-height: var(--tap-target-min);
		color: var(--color-text-muted);
		font-size: var(--font-size-sm);
		text-decoration: none;

		&:hover {
			color: var(--color-brass);
		}

		&:focus-visible {
			@include a11y.focus-ring;
		}
	}
</style>
