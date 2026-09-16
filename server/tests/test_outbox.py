"""`app/outbox.py`'s bounded per-connection queue: the drop-oldest -> collapse-to-`state_sync`
-> dead-connection policy (docs/02-protocol.md §9, docs/00-architecture.md "Outbound
backpressure"). Exercised directly against `BoundedOutbox`, not over a real socket --
constructing genuine slow-consumer backpressure through `starlette.testclient`'s in-memory
transport isn't reliable (there's no real stalled TCP connection to model), so this is the
actual verification of the policy; `tests/test_ws_gameplay.py` covers everything that needs a
live socket.
"""

from __future__ import annotations

from app.outbox import BoundedOutbox


def _frame(t: str, seq: int) -> dict[str, object]:
    return {"v": 1, "t": t, "seq": seq, "ts": 0, "d": {}}


def test_push_under_capacity_keeps_everything_in_order() -> None:
    outbox = BoundedOutbox(maxsize=4)
    for i in range(3):
        outbox.push(_frame("draw", i))
    assert not outbox.dead
    assert [f["seq"] for f in outbox._frames] == [0, 1, 2]  # type: ignore[attr-defined]


def test_overflow_drops_non_critical_frames_and_collapses_to_a_resynced_state_sync() -> None:
    resynced = []

    def resync() -> None:
        resynced.append(True)
        outbox.push(_frame("state_sync", 999))

    outbox = BoundedOutbox(maxsize=4, resync=resync)
    outbox.push(_frame("draw", 1))
    outbox.push(_frame("discard", 2))
    outbox.push(_frame("turn", 3))
    outbox.push({"v": 1, "t": "ack", "seq": 4, "ts": 0, "d": {"id": "c-1", "ok": True}})
    assert not outbox.dead

    outbox.push(_frame("draw", 5))  # 5th frame over a maxsize-4 queue -- triggers overflow

    assert resynced == [True]
    remaining = list(outbox._frames)  # type: ignore[attr-defined]
    types = [f["t"] for f in remaining]
    # every non-critical frame queued before the overflow is gone -- replaced by exactly one
    # fresh state_sync; the ack (critical) survived.
    assert types == ["ack", "state_sync"]
    assert not outbox.dead


def test_overflow_with_only_critical_frames_queued_marks_the_connection_dead() -> None:
    outbox = BoundedOutbox(maxsize=2, resync=lambda: None)
    outbox.push({"v": 1, "t": "ack", "seq": 1, "ts": 0, "d": {"id": "a", "ok": True}})
    outbox.push({"v": 1, "t": "ack", "seq": 2, "ts": 0, "d": {"id": "b", "ok": True}})
    assert not outbox.dead

    outbox.push({"v": 1, "t": "ack", "seq": 3, "ts": 0, "d": {"id": "c", "ok": True}})

    assert outbox.dead  # nothing droppable -- a dead peer, not a slow one


def test_push_after_dead_is_a_noop() -> None:
    outbox = BoundedOutbox(maxsize=1, resync=lambda: None)
    outbox.push({"v": 1, "t": "ack", "seq": 1, "ts": 0, "d": {"id": "a", "ok": True}})
    outbox.push({"v": 1, "t": "ack", "seq": 2, "ts": 0, "d": {"id": "b", "ok": True}})
    assert outbox.dead
    before = list(outbox._frames)  # type: ignore[attr-defined]

    outbox.push({"v": 1, "t": "ack", "seq": 3, "ts": 0, "d": {"id": "c", "ok": True}})

    assert list(outbox._frames) == before  # type: ignore[attr-defined]


async def test_get_drains_in_order_then_returns_none_after_close() -> None:
    outbox = BoundedOutbox(maxsize=4)
    outbox.push(_frame("draw", 1))
    outbox.push(_frame("discard", 2))

    first = await outbox.get()
    second = await outbox.get()
    assert first is not None and first["seq"] == 1
    assert second is not None and second["seq"] == 2

    outbox.close()
    assert await outbox.get() is None
