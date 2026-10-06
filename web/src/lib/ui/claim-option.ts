import type { ClaimKind, ClaimOption } from './ClaimButtons.svelte';
import { tileOptionAriaLabel } from '$lib/table/tile-name';
import { m } from '$lib/paraglide/messages.js';

function claimKindLabel(kind: ClaimKind): string {
	switch (kind) {
		case 'pass':
			return m.claimOption_passLabel();
		case 'chow':
			return m.claimOption_chowLabel();
		case 'pung':
			return m.claimOption_pungLabel();
		case 'kong':
			return m.claimOption_kongLabel();
		case 'win':
			return m.claimOption_winLabel();
	}
}

/** Visible label: the kind only. Tiles render as TileFace previews beside it. */
export function claimOptionLabel(option: ClaimOption): string {
	return claimKindLabel(option.kind);
}

/** Accessible name; `undefined` when the visible label already says everything. */
export function claimOptionAriaLabel(option: ClaimOption): string | undefined {
	return option.tiles?.length
		? tileOptionAriaLabel(claimKindLabel(option.kind), option.tiles)
		: undefined;
}

// index included because two chow options can otherwise share the same (kind, tiles); tiles
// rarely repeat across options but the index guarantees uniqueness regardless.
export function claimOptionKey(option: ClaimOption, index: number): string {
	return `${index}:${option.kind}:${option.tiles?.join(',') ?? ''}`;
}
