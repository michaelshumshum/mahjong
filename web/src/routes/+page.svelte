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
	<h1 class="sr-only">{m.lobby_title()}</h1>
	<div class="actions">
		<button
			type="button"
			class="primary"
			data-testid="lobby-create-table"
			onclick={() => (showCreateDialog = true)}
		>
			{m.lobby_createTableButton()}
		</button>
		<a class="secondary" data-testid="lobby-join-game-link" href="/tables"
			>{m.lobby_joinGameLink()}</a
		>
		<button
			type="button"
			class="secondary"
			data-testid="lobby-practice-bots"
			onclick={() => (showPracticeDialog = true)}
		>
			{m.lobby_practiceButton()}
		</button>
		<div class="row">
			<button
				type="button"
				class="secondary"
				data-testid="lobby-guide"
				onclick={() => (showGuide = true)}
			>
				{m.lobby_guideButton()}
			</button>
			<button
				type="button"
				class="secondary"
				data-testid="lobby-language"
				onclick={() => setLocale(getLocale() === 'en' ? 'zh-Hant' : 'en')}
			>
				{m.lobby_languageButton()}
			</button>
		</div>
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
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

	.sr-only {
		position: absolute;
		width: 1px;
		height: 1px;
		overflow: hidden;
		clip: rect(0 0 0 0);
		white-space: nowrap;
	}

	.lobby {
		position: relative;
		z-index: var(--z-hud);
		display: flex;
		align-items: flex-end;
		justify-content: center;
		min-height: 100dvh;
		padding: var(--space-8) var(--space-5);

		@include layout.phone-only {
			align-items: center;
		}
	}

	.actions {
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
		width: min(20rem, 100%);
	}

	.row {
		display: flex;
		gap: var(--space-3);

		> .secondary {
			flex: 1 1 0;
			min-width: 0;
			font-size: var(--font-size-base);
			padding-inline: var(--space-2);
		}
	}

	.primary,
	.secondary {
		font: inherit;
		font-size: var(--font-size-lg);
		padding: var(--space-3) var(--space-4);
		min-height: var(--tap-target-min);
		cursor: pointer;
	}

	.primary {
		@include buttons.btn-primary;
	}

	.secondary {
		@include buttons.btn-secondary;
	}

	a.secondary {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		text-decoration: none;
	}
</style>
