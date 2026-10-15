"""Client->server frame builders for WebSocket e2e tests."""

import itertools

from app.clock import now_ms
from mahjong_core.tiles import TileType, tile_ids_for_type

_id_gen = itertools.count(1)


def msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": now_ms(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def next_id() -> str:
    return f"c-{next(_id_gen)}"


def hello(
    *, last_seq: int | None = None, seat: int | None = None, secret: str | None = None
) -> dict[str, object]:
    d: dict[str, object] = {"client_version": "test"}
    if last_seq is not None:
        d["last_seq"] = last_seq
    if seat is not None:
        d["seat"] = seat
    if secret is not None:
        d["secret"] = secret
    return msg("hello", d)


def first_tile_ids(*types: TileType, count: int) -> tuple[int, ...]:
    """The first `count` ids across every copy of `types`, in order."""
    ids = [tid for t in types for tid in tile_ids_for_type(t)]
    return tuple(ids[:count])
