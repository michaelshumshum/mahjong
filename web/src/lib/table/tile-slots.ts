// Positional slot-identity model for an opponent's concealed hand (docs/03-frontend.md §4).
// The protocol never gives an opponent's tiles a real identity until they're revealed (a
// discard, an open meld, or hand end) — the client tracks a stable per-slot key instead, so
// Svelte's keyed {#each} preserves DOM element continuity across draw/discard/kong
// transitions regardless of which physical tile a slot "really" holds.
//
// The doc's rule ("if seat:drawn exists, it left; otherwise the rightmost concealed slot
// (seat:12) morphs instead, and slots above it shift down") reduces to one operation once you
// notice both cases name the *same position*: whichever slot is currently last in the array,
// drawn-slot or not. Popping from the end is the whole rule — no surviving slot's key ever
// changes, so there is nothing to "shift" except the one that departs.

export interface Slot {
	/** Stable across this slot's lifetime; never reused, never reassigned to a different slot. */
	key: number;
}

export interface SlotState {
	/** Concealed slots in display order; the last entry is the drawn tile, if any. */
	slots: readonly Slot[];
	/** Monotonic counter for the next slot's key. */
	nextKey: number;
}

export function initialSlotState(concealedCount: number): SlotState {
	if (concealedCount < 0) throw new Error('concealedCount must be >= 0');
	const slots = Array.from({ length: concealedCount }, (_, key) => ({ key }));
	return { slots, nextKey: concealedCount };
}

/** draw {seat}: append seat:drawn — the "held apart" 14th tile, same convention as your own hand. */
export function pushDrawnSlot(state: SlotState): SlotState {
	return {
		slots: [...state.slots, { key: state.nextKey }],
		nextKey: state.nextKey + 1
	};
}

/**
 * A discard from this seat: pop the last slot. Covers both branches of §4's rule (the drawn
 * slot if present, otherwise the rightmost concealed slot) since they're the same position.
 */
export function popSlotForDiscard(state: SlotState): { left: Slot; remaining: SlotState } {
	if (state.slots.length === 0) throw new Error('no concealed slots to discard from');
	const left = state.slots[state.slots.length - 1];
	return {
		left,
		remaining: { slots: state.slots.slice(0, -1), nextKey: state.nextKey }
	};
}

/**
 * concealed_kong {seat, count: 4}: the drawn slot (if present) plus the 3 rightmost concealed
 * slots — the same "pop from the end" rule, extended to 4 (§4).
 */
export function popSlotsForConcealedKong(state: SlotState): {
	kong: readonly Slot[];
	remaining: SlotState;
} {
	if (state.slots.length < 4) throw new Error('need at least 4 concealed slots for a kong');
	return {
		kong: state.slots.slice(-4),
		remaining: { slots: state.slots.slice(0, -4), nextKey: state.nextKey }
	};
}
