// what this seat may do right now, derived from the store's raw legal_actions / claim offer.
// pure, so the table page and a static snapshot (no socket) derive the same options.

import type { ClaimOption } from '$lib/game/types';
import type { ClientGameState } from '$lib/game/state';
import { m } from '$lib/paraglide/messages.js';
import { tileIdToCode } from './tile-code';
import type { ClaimWindowView, DeclareOption } from './view-types';

type LegalAction = ClientGameState['legalActions'][number];

export interface DeclareIntents {
	win: () => void;
	concealedKong: (tiles: number[]) => void;
	addedKong: (tiles: number[]) => void;
}

export function legalDiscardIds(legalActions: readonly LegalAction[]): Set<number> {
	return new Set(legalActions.filter((a) => a.kind === 'discard').map((a) => a.tile_id as number));
}

// legal_actions' own kind tags are the longer declare_*/claim_* forms; the wire declare{kind}
// intent takes the shorter concealed_kong|added_kong|win -- two vocabularies, one concept.
export function legalDeclareOptions(
	legalActions: readonly LegalAction[],
	intents: DeclareIntents
): DeclareOption[] {
	const options: DeclareOption[] = [];
	for (const action of legalActions) {
		const meld = action.meld as { tiles?: number[] } | undefined;
		if (action.kind === 'declare_win') {
			// a declare{win} option only ever appears after this seat's own draw (a discard/
			// kong-rob win goes through the claim window, not here) -- always a self-draw.
			options.push({
				key: 'win',
				label: m.tablePage_declareWinLabel(),
				onClick: () => intents.win(),
				hero: true
			});
		} else if (action.kind === 'declare_concealed_kong' && meld?.tiles) {
			const tiles = meld.tiles;
			options.push({
				key: `ck-${tiles.join(',')}`,
				label: m.tablePage_declareConcealedKongLabel(),
				tiles: tiles.map(tileIdToCode),
				onClick: () => intents.concealedKong(tiles)
			});
		} else if (action.kind === 'declare_added_kong' && meld?.tiles) {
			const tiles = meld.tiles;
			options.push({
				key: `ak-${tiles.join(',')}`,
				label: m.tablePage_declareAddedKongLabel(),
				tiles: tiles.map(tileIdToCode),
				onClick: () => intents.addedKong(tiles)
			});
		}
	}
	return options;
}

export function legalClaimOptions(claimWindow: ClaimWindowView | null): ClaimOption[] | null {
	return claimWindow?.yourOptions
		? claimWindow.yourOptions.map((o) => ({ kind: o.kind, tiles: o.tiles }))
		: null;
}

// the view model's `yourOptions` are display-only (TileCode, no id) -- recover the raw,
// real-tile_id option `live-view.ts` built them from to submit the actual `claim` intent.
export function findRawClaimOption(
	rawOptions: readonly Record<string, unknown>[] | null,
	option: ClaimOption
): Record<string, unknown> | undefined {
	if (!rawOptions) return undefined;
	const candidates = rawOptions.filter((o) => o.kind === option.kind);
	if (candidates.length <= 1) return candidates[0];
	// only a chow claim can have more than one candidate for the same discard -- disambiguate
	// by which tile codes the option actually names.
	const wanted = new Set(option.tiles ?? []);
	return candidates.find((o) => {
		const ids = (o.tiles as number[] | undefined) ?? [];
		const codes = new Set(ids.map(tileIdToCode));
		return codes.size === wanted.size && [...codes].every((c) => wanted.has(c));
	});
}
