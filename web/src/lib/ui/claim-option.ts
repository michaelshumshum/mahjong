import type { ClaimKind, ClaimOption } from './ClaimButtons.svelte';

const LABEL: Record<ClaimKind, string> = {
	pass: 'Pass',
	chow: 'Chow',
	pung: 'Pung',
	kong: 'Kong',
	win: 'Win'
};

export function claimOptionLabel(option: ClaimOption): string {
	return option.tiles?.length
		? `${LABEL[option.kind]} ${option.tiles.join('-')}`
		: LABEL[option.kind];
}

// index included because two chow options can otherwise share the same (kind, tiles); tiles
// rarely repeat across options but the index guarantees uniqueness regardless.
export function claimOptionKey(option: ClaimOption, index: number): string {
	return `${index}:${option.kind}:${option.tiles?.join(',') ?? ''}`;
}
