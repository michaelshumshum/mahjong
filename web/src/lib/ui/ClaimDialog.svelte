<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import type { TileCode } from '../table/tile-code';
	import type { ClaimOption } from './ClaimButtons.svelte';
	import { claimOptionKey, claimOptionLabel } from './claim-option';
	import DialogTimer from './DialogTimer.svelte';

	let {
		discardTile,
		discarderName,
		options,
		durationMs,
		onChoose
	}: {
		discardTile: TileCode | null;
		discarderName: string | null;
		options: ClaimOption[];
		durationMs: number;
		onChoose: (option: ClaimOption) => void;
	} = $props();

	interface PreviewTile {
		code: TileCode;
		claimed: boolean;
	}

	// the meld an option would complete: its hand tiles plus the claimed discard, sorted for a
	// chow (same suit, single-digit rank, so a plain string sort reads left-to-right ascending)
	// -- pung/kong tiles are already identical so order is moot. `win`/`pass` have no fixed meld
	// shape to preview (a win's actual hand is the post-win FaanBreakdown overlay's job).
	function meldPreview(option: ClaimOption): PreviewTile[] | null {
		if (!discardTile || !option.tiles?.length) return null;
		const tiles: PreviewTile[] = [
			...option.tiles.map((code) => ({ code, claimed: false })),
			{ code: discardTile, claimed: true }
		];
		if (option.kind === 'chow') tiles.sort((a, b) => a.code.localeCompare(b.code));
		return tiles;
	}

	// deadline reached with no explicit choice: resolve the same way the server does on its own
	// claim-window timeout (docs/02-protocol.md §4, "PASS on claim timeout") -- `options` always
	// carries a `pass` entry (docs/02-protocol.md's `claim_offer` row), so this reuses the exact
	// `onChoose` path a manual Pass click already takes, rather than inventing a second one.
	function handleTimeout(): void {
		const passOption = options.find((option) => option.kind === 'pass');
		if (passOption) onChoose(passOption);
	}
</script>

<div class="claim-dialog" role="dialog" aria-label="Claim options">
	<div class="claim-dialog-timer">
		<DialogTimer {durationMs} size={40} onClose={handleTimeout} />
	</div>

	<div class="claim-dialog-header">
		<h2>Claim</h2>
		{#if discardTile}
			<p class="claim-dialog-subtitle">
				{discarderName ?? 'Someone'} discarded
				<span class="claim-dialog-tile"><TileFace code={discardTile} /></span>
			</p>
		{/if}
	</div>

	<div class="claim-options" role="group" aria-label="Claim options">
		{#each options as option, index (claimOptionKey(option, index))}
			{@const meld = meldPreview(option)}
			<div class="claim-option">
				{#if meld}
					<div class="claim-meld" aria-hidden="true">
						{#each meld as tile, ti (ti)}
							<div class="claim-meld-tile" class:claim-meld-tile--claimed={tile.claimed}>
								<TileFace code={tile.code} />
							</div>
						{/each}
					</div>
				{/if}
				<button
					type="button"
					class="claim-btn claim-btn--{option.kind}"
					onclick={() => onChoose(option)}
				>
					{claimOptionLabel(option)}
				</button>
			</div>
		{/each}
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';

	.claim-dialog {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-3);
		width: 100%;
		max-width: 28rem;
		padding: var(--space-4);
		background: var(--color-surface-raised);
		text-align: center;
		@include buttons.panel-elevated;
	}

	.claim-dialog-timer {
		pointer-events: none;
	}

	.claim-dialog-header {
		display: flex;
		flex-direction: column;
		gap: var(--space-1);
	}

	.claim-dialog-header h2 {
		margin: 0;
		font-size: var(--font-size-lg);
	}

	.claim-dialog-subtitle {
		display: flex;
		align-items: center;
		justify-content: center;
		gap: var(--space-1);
		margin: 0;
		color: var(--color-text-muted);
	}

	.claim-dialog-tile {
		display: inline-flex;
		height: 1.5em;
	}

	.claim-dialog-tile :global(.tile-face) {
		height: 100%;
	}

	.claim-options {
		display: flex;
		flex-wrap: wrap;
		align-items: flex-end;
		justify-content: center;
		gap: var(--space-4);
	}

	.claim-option {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: var(--space-2);
	}

	.claim-meld {
		display: flex;
		gap: 2px;
	}

	.claim-meld-tile {
		height: clamp(36px, 8vw, 52px);
	}

	.claim-meld-tile :global(.tile-face) {
		height: 100%;
	}

	// the one physical tile that came from the discard, not this seat's own hand -- a quiet
	// accent ring rather than a full recolor, since it sits right next to identical siblings in
	// a pung/kong preview and only needs to read as "this one", not draw the eye on its own.
	.claim-meld-tile--claimed :global(.tile-face) {
		outline: 2px solid var(--color-accent);
		outline-offset: 1px;
	}

	.claim-btn {
		min-width: 44px;
		min-height: 44px;
		padding: var(--space-2) var(--space-4);
		font: inherit;
		cursor: pointer;
	}

	.claim-btn--chow,
	.claim-btn--pung,
	.claim-btn--kong {
		@include buttons.btn-secondary;
	}

	.claim-btn--pass {
		@include buttons.btn-ghost;
	}

	.claim-btn--win {
		@include buttons.btn-primary;
	}

	.claim-btn:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
