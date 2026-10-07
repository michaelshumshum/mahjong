import type { MeldKind, MockGameState } from '$lib/table/mock-game-state';
import type { TileCode } from '$lib/table/tile-code';
import { tileName } from '$lib/table/tile-name';
import { m } from '$lib/paraglide/messages.js';

/** What the announcer compares between renders -- a plain snapshot, no proxies. */
export interface AnnounceSnapshot {
	handKey: string;
	you: number;
	names: string[];
	discards: TileCode[][];
	meldKinds: MeldKind[][];
	claim: { kind: 'discard' | 'kong_rob'; sourceSeat: number; tile: TileCode } | null;
	yourTurn: boolean;
	handResult: { outcome: 'win' | 'exhaustive_draw'; winner: number | null } | null;
}

// a spectator has no "you": every seat is announced by name.
export function announceSnapshot(
	state: MockGameState,
	handKey: string,
	yourTurn: boolean,
	spectating: boolean
): AnnounceSnapshot {
	const bySeat = [...state.seats].sort((a, b) => a.seat - b.seat);
	const window = state.claimWindow;
	return {
		handKey,
		you: spectating ? -1 : state.you,
		names: bySeat.map((s) => s.name),
		discards: bySeat.map((s) => [...s.discards]),
		meldKinds: bySeat.map((s) => s.melds.map((meld) => meld.kind)),
		claim: window?.yourOptions?.length
			? { kind: window.kind, sourceSeat: window.sourceSeat, tile: window.tile }
			: null,
		yourTurn,
		handResult: state.handResult
			? { outcome: state.handResult.outcome, winner: state.handResult.winner ?? null }
			: null
	};
}

function meldLabel(kind: MeldKind): string {
	switch (kind) {
		case 'chow':
			return m.claimOption_chowLabel();
		case 'pung':
			return m.claimOption_pungLabel();
		case 'exposed_kong':
		case 'added_kong':
			return m.claimOption_kongLabel();
		case 'concealed_kong':
			return m.tablePage_declareConcealedKongLabel();
	}
}

// live-region lines for what changed (frontend.md §9 verbosity table). a hand/scenario change
// only re-baselines -- a jump between snapshots is not an event.
export function announcementsBetween(
	prev: AnnounceSnapshot | null,
	next: AnnounceSnapshot,
	everyDiscard: boolean
): string[] {
	if (!prev || prev.handKey !== next.handKey) return [];
	const lines: string[] = [];
	const name = (seat: number) => (seat === next.you ? m.announcer_you() : next.names[seat]);

	if (everyDiscard) {
		next.discards.forEach((pool, seat) => {
			for (const code of pool.slice(prev.discards[seat]?.length ?? 0)) {
				lines.push(m.announcer_discarded({ name: name(seat), tile: tileName(code) }));
			}
		});
	}

	if (next.claim && !prev.claim) {
		const { kind, sourceSeat, tile } = next.claim;
		const args = { name: name(sourceSeat), tile: tileName(tile) };
		if (kind === 'kong_rob') lines.push(m.announcer_kongRob(args));
		else if (!everyDiscard) lines.push(m.announcer_discarded(args));
		lines.push(m.announcer_claimAvailable());
	}

	next.meldKinds.forEach((kinds, seat) => {
		for (const kind of kinds.slice(prev.meldKinds[seat]?.length ?? 0)) {
			const meld = meldLabel(kind);
			lines.push(
				kind === 'concealed_kong' || kind === 'added_kong'
					? m.announcer_declared({ name: name(seat), meld })
					: m.announcer_called({ name: name(seat), meld })
			);
		}
	});

	if (next.yourTurn && !prev.yourTurn) lines.push(m.announcer_yourTurn());

	if (next.handResult && !prev.handResult) {
		const { outcome, winner } = next.handResult;
		if (outcome !== 'win' || winner === null) lines.push(m.announcer_handDraw());
		else if (winner === next.you) lines.push(m.announcer_youWin());
		else lines.push(m.announcer_handWon({ name: next.names[winner] }));
	}

	return lines;
}
