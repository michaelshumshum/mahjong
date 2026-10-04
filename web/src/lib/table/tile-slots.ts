// positional slot-identity model (docs/frontend.md §4): a stable per-slot key stands in for an
// opponent's concealed tile until reveal -- both of §4's resolution rules always name the last slot, so popping from the end is the whole rule.

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

/** draw {seat}: append seat:drawn — the held-apart 14th tile. */
export function pushDrawnSlot(state: SlotState): SlotState {
	return {
		slots: [...state.slots, { key: state.nextKey }],
		nextKey: state.nextKey + 1
	};
}

/** A discard from this seat: pop the last slot -- covers both branches of §4's rule. */
export function popSlotForDiscard(state: SlotState): { left: Slot; remaining: SlotState } {
	if (state.slots.length === 0) throw new Error('no concealed slots to discard from');
	const left = state.slots[state.slots.length - 1];
	return {
		left,
		remaining: { slots: state.slots.slice(0, -1), nextKey: state.nextKey }
	};
}

/** concealed_kong {seat, count: 4}: same pop-from-the-end rule, extended to 4 (§4). */
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
