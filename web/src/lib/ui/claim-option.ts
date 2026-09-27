import type { ClaimKind, ClaimOption } from './ClaimButtons.svelte';
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

export function claimOptionLabel(option: ClaimOption): string {
	const label = claimKindLabel(option.kind);
	return option.tiles?.length ? `${label} ${option.tiles.join('-')}` : label;
}

// index included because two chow options can otherwise share the same (kind, tiles); tiles
// rarely repeat across options but the index guarantees uniqueness regardless.
export function claimOptionKey(option: ClaimOption, index: number): string {
	return `${index}:${option.kind}:${option.tiles?.join(',') ?? ''}`;
}
