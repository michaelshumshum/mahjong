import { describe, expect, it } from 'vitest';
import {
	initialSlotState,
	popSlotForDiscard,
	popSlotsForConcealedKong,
	pushDrawnSlot
} from './tile-slots';

describe('initialSlotState', () => {
	it('creates one slot per concealed tile, keyed 0..n-1', () => {
		const state = initialSlotState(13);
		expect(state.slots).toHaveLength(13);
		expect(state.slots.map((s) => s.key)).toEqual([...Array(13).keys()]);
		expect(state.nextKey).toBe(13);
	});

	it('rejects a negative count', () => {
		expect(() => initialSlotState(-1)).toThrow();
	});

	it('allows zero concealed tiles', () => {
		expect(initialSlotState(0).slots).toEqual([]);
	});
});

describe('pushDrawnSlot', () => {
	it('appends a new slot with the next key and does not mutate the input', () => {
		const before = initialSlotState(13);
		const after = pushDrawnSlot(before);

		expect(before.slots).toHaveLength(13); // unchanged
		expect(after.slots).toHaveLength(14);
		expect(after.slots[13]).toEqual({ key: 13 });
		expect(after.nextKey).toBe(14);
	});

	it('never reuses a key, even after several draws', () => {
		let state = initialSlotState(0);
		for (let i = 0; i < 5; i++) state = pushDrawnSlot(state);
		expect(state.slots.map((s) => s.key)).toEqual([0, 1, 2, 3, 4]);
	});
});

describe('popSlotForDiscard', () => {
	it('with a drawn slot present, that slot is the one that left (§4: "if seat:drawn exists, it left")', () => {
		const drawn = pushDrawnSlot(initialSlotState(13)); // 14 slots, last key = 13
		const { left, remaining } = popSlotForDiscard(drawn);

		expect(left).toEqual({ key: 13 });
		expect(remaining.slots).toHaveLength(13);
	});

	it('with no drawn slot, the rightmost concealed slot leaves (§4: "otherwise seat:12")', () => {
		const state = initialSlotState(13); // no drawn slot, last key = 12
		const { left, remaining } = popSlotForDiscard(state);

		expect(left).toEqual({ key: 12 });
		expect(remaining.slots).toHaveLength(12);
	});

	it('never changes any surviving slot’s key ("nothing to shift except the one that departs")', () => {
		const state = initialSlotState(13);
		const { remaining } = popSlotForDiscard(state);
		expect(remaining.slots.map((s) => s.key)).toEqual([...Array(12).keys()]);
	});

	it('preserves nextKey across a discard (no new slots created)', () => {
		const state = initialSlotState(13);
		const { remaining } = popSlotForDiscard(state);
		expect(remaining.nextKey).toBe(13);
	});

	it('throws when there are no concealed slots left', () => {
		expect(() => popSlotForDiscard(initialSlotState(0))).toThrow();
	});

	it('round-trip: draw then discard returns to the original slot set', () => {
		const original = initialSlotState(13);
		const { remaining } = popSlotForDiscard(pushDrawnSlot(original));
		expect(remaining.slots).toEqual(original.slots);
	});
});

describe('popSlotsForConcealedKong', () => {
	it('takes the drawn slot plus the 3 rightmost concealed slots', () => {
		const drawn = pushDrawnSlot(initialSlotState(13)); // keys 0..12 concealed, 13 drawn
		const { kong, remaining } = popSlotsForConcealedKong(drawn);

		expect(kong.map((s) => s.key)).toEqual([10, 11, 12, 13]);
		expect(remaining.slots.map((s) => s.key)).toEqual([...Array(10).keys()]);
	});

	it('without a drawn slot, takes the 4 rightmost concealed slots', () => {
		const { kong, remaining } = popSlotsForConcealedKong(initialSlotState(13));
		expect(kong.map((s) => s.key)).toEqual([9, 10, 11, 12]);
		expect(remaining.slots).toHaveLength(9);
	});

	it('throws with fewer than 4 concealed slots', () => {
		expect(() => popSlotsForConcealedKong(initialSlotState(3))).toThrow();
	});

	it('never changes a surviving slot’s key', () => {
		const state = initialSlotState(13);
		const { remaining } = popSlotsForConcealedKong(state);
		expect(remaining.slots).toEqual(state.slots.slice(0, 9));
	});
});
