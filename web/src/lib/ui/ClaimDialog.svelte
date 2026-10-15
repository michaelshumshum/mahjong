<script lang="ts">
	import TileFace from '../table/TileFace.svelte';
	import type { TileCode } from '../table/tile-code';
	import type { ClaimOption } from '$lib/game/types';
	import { claimOptionAriaLabel, claimOptionKey, claimOptionLabel } from './claim-option';
	import DialogTimer from './DialogTimer.svelte';
	import { m } from '$lib/paraglide/messages.js';

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

	// the meld an option would complete: hand tiles plus the claimed discard, sorted for a chow
	// (plain string sort reads left-to-right ascending; pung/kong tiles are identical already).
	function meldPreview(option: ClaimOption): PreviewTile[] | null {
		if (!discardTile || !option.tiles?.length) return null;
		const tiles: PreviewTile[] = [
			...option.tiles.map((code) => ({ code, claimed: false })),
			{ code: discardTile, claimed: true }
		];
		if (option.kind === 'chow') tiles.sort((a, b) => a.code.localeCompare(b.code));
		return tiles;
	}

	// pass renders on its own row below the rest, so number keys index the non-pass options only.
	const callOptions = $derived(options.filter((option) => option.kind !== 'pass'));
	const passOption = $derived(options.find((option) => option.kind === 'pass'));

	// deadline reached with no explicit choice: resolve the same way the server does on its own
	// timeout, reusing the exact onChoose path a manual Pass click takes.
	function handleTimeout(): void {
		if (passOption) onChoose(passOption);
	}

	// 1-4 pick the Nth call option by position, Esc passes -- the same onChoose path a click takes.
	// the host ModalDialog has no onCancel, so its own Escape close request is a no-op here.
	function handleKeydown(e: KeyboardEvent): void {
		if (e.key === 'Escape') {
			e.preventDefault();
			if (passOption) onChoose(passOption);
			return;
		}
		const index = Number(e.key) - 1;
		if (Number.isInteger(index) && index >= 0 && index < callOptions.length) {
			onChoose(callOptions[index]);
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="claim-dialog">
	<div class="claim-dialog-timer">
		<DialogTimer {durationMs} size={40} onClose={handleTimeout} />
	</div>

	<div class="claim-dialog-header">
		<h2>{m.claimDialog_heading()}</h2>
		{#if discardTile}
			<p class="claim-dialog-subtitle">
				{m.claimDialog_discardedLabel({ name: discarderName ?? m.claimDialog_someoneLabel() })}
				<span class="claim-dialog-tile"><TileFace code={discardTile} /></span>
			</p>
		{/if}
	</div>

	<div class="claim-options" role="group" aria-label={m.claimDialog_optionsGroupAriaLabel()}>
		<div class="claim-calls">
			{#each callOptions as option, index (claimOptionKey(option, index))}
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
						aria-label={claimOptionAriaLabel(option)}
						onclick={() => onChoose(option)}
					>
						<span class="claim-btn-key" aria-hidden="true">{index + 1}</span>
						<span class="claim-btn-label">{claimOptionLabel(option)}</span>
					</button>
				</div>
			{/each}
		</div>
		{#if passOption}
			<!-- ModalDialog focuses [data-autofocus] once on open: a safe default under the keyboard. -->
			<button
				data-autofocus
				type="button"
				class="claim-btn claim-btn--pass"
				aria-label={claimOptionAriaLabel(passOption)}
				onclick={() => onChoose(passOption)}
			>
				<span class="claim-btn-key" aria-hidden="true">{m.claimDialog_passEscHint()}</span>
				<span class="claim-btn-label">{claimOptionLabel(passOption)}</span>
			</button>
		{/if}
	</div>
</div>

<style lang="scss">
	@use '$lib/styles/buttons';
	@use '$lib/styles/layout';

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
		flex-direction: column;
		align-items: stretch;
		gap: var(--space-3);
		width: 100%;
	}

	.claim-calls {
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

	// the one tile that came from the discard -- a quiet accent ring, not a full recolor, since
	// it sits next to identical siblings and only needs to read as "this one".
	.claim-meld-tile--claimed :global(.tile-face) {
		outline: 2px solid var(--color-accent);
		outline-offset: 1px;
	}

	// each option is a big button, not a plain label -- key badge and label.
	.claim-btn {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 2px;
		min-height: var(--tap-target-min);
		padding: var(--space-2) var(--space-3);
		font: inherit;
		cursor: pointer;
	}

	.claim-btn-key {
		position: absolute;
		top: var(--space-1);
		right: var(--space-1);
		padding: 0 0.3rem;
		border-radius: var(--radius-sm);
		background: rgb(0 0 0 / 0.25);
		font-size: var(--font-size-xs);
		font-variant-numeric: tabular-nums;
		opacity: 0.8;
	}

	.claim-btn-label {
		font-weight: 700;
	}

	// every call button shares one fixed size; only pass differs.
	.claim-calls .claim-btn {
		width: 5.5rem;
	}

	.claim-btn--chow,
	.claim-btn--pung,
	.claim-btn--kong {
		@include buttons.btn-secondary;
	}

	.claim-btn--pass {
		@include buttons.btn-ghost;
	}

	// win stands out by colour and the SeatPlate turn-halo glow, not size.
	.claim-btn--win {
		box-shadow: 0 0 0 4px var(--color-accent-glow);
		@include buttons.btn-primary;
	}

	// phone: a bottom sheet instead of a centred card (the host ModalDialog's `sheet` placement).
	@include layout.phone-only {
		.claim-dialog {
			align-self: flex-end;
			width: 100%;
			max-width: 100%;
			border-radius: var(--radius-lg) var(--radius-lg) 0 0;
			padding-bottom: max(var(--space-4), env(safe-area-inset-bottom));
		}
	}

	// phone landscape: one row from the top edge -- timer and header, the calls, then pass -- so
	// the sheet covers the across seat, not your hand.
	@include layout.phone-landscape {
		.claim-dialog {
			display: grid;
			grid-template-columns: auto auto minmax(0, 1fr);
			align-items: center;
			align-self: flex-start;
			gap: var(--space-2) var(--space-4);
			padding: max(var(--space-2), env(safe-area-inset-top)) var(--space-4) var(--space-3);
			border-radius: 0 0 var(--radius-lg) var(--radius-lg);
			text-align: start;
		}

		.claim-dialog-header {
			min-width: 0;
		}

		.claim-options {
			flex-direction: row;
			align-items: flex-end;
		}

		.claim-calls {
			flex-wrap: nowrap;
			gap: var(--space-3);
		}

		.claim-meld-tile {
			height: 36px;
		}

		.claim-btn--pass {
			flex: 1;
			min-width: 6rem;
		}
	}
</style>
