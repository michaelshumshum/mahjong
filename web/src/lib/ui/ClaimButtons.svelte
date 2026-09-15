<script lang="ts">
	import type { TileCode } from '../table/tile-code';

	export type ClaimKind = 'pass' | 'chow' | 'pung' | 'kong' | 'win';

	// mirrors the wire `claim{window_id, choice, tiles?}` shape (docs/02-protocol.md §2):
	// `tiles` only disambiguates `chow` (two options can claim the same discard into
	// different runs, e.g. 4s-5s vs 5s-7s completing a discarded 6s) — no other kind is ever
	// ambiguous once the server has offered it. No `window_id` here: this component is pure
	// presentation, wiring a real offer to a real window is the later integration sub-task.
	export interface ClaimOption {
		kind: ClaimKind;
		tiles?: TileCode[];
	}

	let { options, onChoose }: { options: ClaimOption[]; onChoose: (option: ClaimOption) => void } =
		$props();

	const LABEL: Record<ClaimKind, string> = {
		pass: 'Pass',
		chow: 'Chow',
		pung: 'Pung',
		kong: 'Kong',
		win: 'Win'
	};

	function label(option: ClaimOption): string {
		return option.tiles?.length
			? `${LABEL[option.kind]} ${option.tiles.join('-')}`
			: LABEL[option.kind];
	}

	// index included because two chow options can otherwise share the same (kind, tiles);
	// tiles rarely repeat across options but the index guarantees uniqueness regardless.
	function optionKey(option: ClaimOption, index: number): string {
		return `${index}:${option.kind}:${option.tiles?.join(',') ?? ''}`;
	}
</script>

<div class="claim-buttons" role="group" aria-label="Claim options">
	{#each options as option, index (optionKey(option, index))}
		<button
			type="button"
			class="claim-btn claim-btn--{option.kind}"
			onclick={() => onChoose(option)}
		>
			{label(option)}
		</button>
	{/each}
</div>

<style lang="scss">
	// bottom-center per docs/03-frontend.md §5; fixed rather than relying on a positioned
	// ancestor, since this component isn't slotted into the real table overlay stack yet.
	.claim-buttons {
		position: fixed;
		inset-inline: 0;
		bottom: var(--space-5);
		display: flex;
		justify-content: center;
		gap: var(--space-3);
		z-index: var(--z-overlay);
		pointer-events: none;
	}

	.claim-btn {
		pointer-events: auto;
		min-width: 44px;
		min-height: 44px;
		padding: var(--space-2) var(--space-4);
		border-radius: var(--radius-md);
		border: 1px solid var(--color-border);
		background: var(--color-surface-raised);
		color: var(--color-text);
		font: inherit;
		font-weight: 600;
		cursor: pointer;
	}

	.claim-btn--win {
		background: var(--color-accent);
		border-color: var(--color-accent);
		color: var(--color-bg);
	}

	.claim-btn:focus-visible {
		outline: 2px solid var(--color-accent);
		outline-offset: 2px;
	}
</style>
