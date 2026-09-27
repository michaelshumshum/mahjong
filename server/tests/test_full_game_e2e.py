"""M3's literal done-when gate, closeout audit (docs/05-roadmap.md M3, M2 sub-task 10's
pattern applied to the server): "four scripted WS clients play a full game; killing one
mid-hand and reconnecting resumes correctly from `last_seq`; `test_redaction` proves no seat
ever receives a tile identity it isn't entitled to." `tests/test_ws_gameplay.py` proves one
hand over the wire, `tests/test_reconnect.py` proves reconnect in isolation on hand 1, and
`tests/test_redaction.py` proves redaction by construction -- none of the three ever run
together across more than one hand. This module is the thing that actually does: four WS
clients, one continuous `Table`, four real hands (`EAST_ONLY`, both dealer-repeat flags off, so
the deal rotates 0 -> 1 -> 2 -> 3 unconditionally and the round wrapping back to seat 0
reaches `Phase.GAME_OVER` deterministically -- the cheapest ruleset config that reaches a real
terminal condition), a real claim exchange, a real self-draw win, a real mid-claim-window
disconnect/reconnect in hand 3 (not hand 1 -- closing the actual "reachable only in a later
hand" gap `test_reconnect.py` structurally can't cover on its own), and a `GameRecord` persist
check spanning the whole game's `Table.actions` log, not one hand's worth.

Every hand *after* the first is dealt for real by `Table`'s own `start_next_hand()` -> `_apply`
chain (dealer/prevailing/hand_no/hand_seed all genuinely engine-computed, verified below against
`derive_hand_seed`) -- only each hand's concealed tiles and wall tail are then overwritten with
`table.state = ...` (this repo's established white-box rig convention, `tests/test_table_claims.
py` on) so the rest of that hand can be scripted deterministically over the real wire, the same
way `tests/test_ws_gameplay.py`/`tests/test_game_record_ws.py` already rig one hand each.

Every `ws.receive_json()` below goes through `recv()`, which -- on top of returning the frame
-- positively checks the exact entitlement rules `app/views.py`'s `Entitlement`-annotated wire
types declare (OWN_SEAT tile ids null for every foreign seat, `HandEndWire.winning_hand` null
until `revealed`), live, on every single frame any of the four connections receives over the
whole game -- not just at the specific spots each older test happened to assert on.

Seat 3's `with client.websocket_connect(...) as ws3:` block deliberately ends (rather than
calling `.close()` mid-scenario) right after hand 3's `turn` frames land, to simulate the
disconnect -- `WebSocketTestSession.__enter__` registers its own `close()` as an exit callback,
so a manual `.close()` earlier would double-close on the outer `with`'s teardown; ending the
narrower `with` block here is this repo's own established way to disconnect exactly one seat
(`tests/test_reconnect.py`'s `_drain_teardown_disconnects` closes three seats the same way, by
exiting their shared `with` block) without touching the others.
"""

from __future__ import annotations

import asyncio
import dataclasses
import itertools
import time
import uuid
from pathlib import Path
from typing import Any, cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from starlette.testclient import WebSocketTestSession

from app.db.models import Base, GameRecord
from app.db.session import make_engine, make_session_factory
from app.main import app
from app.ws import get_table
from mahjong_core.actions import action_from_dict
from mahjong_core.config import DEFAULT_RULESET, RuleSet
from mahjong_core.engine import ENGINE_VERSION, new_game
from mahjong_core.state import GameState, Phase, derive_hand_seed
from mahjong_core.tiles import TileType, tile_ids_for_type

_id_gen = itertools.count(1)

# both repeat flags off + EAST_ONLY rotates dealer 0->1->2->3 unconditionally and ends the game
# on dealer 0 again -- exactly 4 hands, deterministically, the cheapest multi-hand terminal case.
_GAME_RULESET = dataclasses.replace(
    DEFAULT_RULESET,
    dealer_repeat_on_win=False,
    dealer_repeat_on_draw=False,
    # every seat here is "connected", not bot/autoplay, so nothing ever sends a real
    # hand_end_ack; 0 lets Table.run() advance past each hold on its own next tick.
    hand_end_seconds=0,
)

_MAN_1 = tile_ids_for_type(TileType.MAN_1)
_MAN_2 = tile_ids_for_type(TileType.MAN_2)
_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)
_MAN_7 = tile_ids_for_type(TileType.MAN_7)
_MAN_8 = tile_ids_for_type(TileType.MAN_8)
_MAN_9 = tile_ids_for_type(TileType.MAN_9)
_PIN_1 = tile_ids_for_type(TileType.PIN_1)


def _ts() -> int:
    return time.time_ns() // 1_000_000


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": _ts(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def _next_id() -> str:
    return f"c-{next(_id_gen)}"


def _tiles(*types: TileType, count: int) -> tuple[int, ...]:
    ids = [tid for t in types for tid in tile_ids_for_type(t)]
    return tuple(ids[:count])


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _rig_hands(state: GameState, hands: dict[int, tuple[int, ...]]) -> GameState:
    """Overwrite each listed seat's concealed tiles (clearing discards/flowers) and empty the
    wall tail -- the shared tail of every hand rig below, once `state` is already a real,
    engine-dealt `AWAIT_ACTION` state for the hand being scripted."""
    for seat, concealed in hands.items():
        state = _with_seat(state, seat, concealed=concealed, discards=(), flowers=())
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


def _check_redaction(frame: dict[str, Any], seat: int) -> None:
    """Live entitlement check, applied to every frame every connection receives (`_recv()`
    below) -- the `app/views.py` `Entitlement` rules a real bug would violate, checked against
    the actual wire content rather than trusting `test_redaction.py`'s schema walk alone."""
    d = frame.get("d")
    if not isinstance(d, dict):
        return
    t = frame.get("t")
    if t in ("draw", "kong_replace"):
        if d.get("seat") != seat:
            assert d.get("tile_id") is None, f"{t} leaked a foreign tile_id to seat {seat}: {d}"
        else:
            assert d.get("tile_id") is not None
    elif t == "meld" and d.get("meld_kind") == "concealed_kong":
        if d.get("seat") != seat:
            assert d.get("tiles") is None, f"concealed_kong leaked tiles to seat {seat}: {d}"
            assert d.get("count") is not None
        else:
            assert d.get("tiles") is not None
    elif t == "hand_end":
        if d.get("outcome") == "win":
            assert d.get("revealed") is True
        else:
            assert d.get("revealed") is False
            assert d.get("winning_hand") is None


def _recv(ws: WebSocketTestSession, seat: int) -> dict[str, Any]:
    frame = cast("dict[str, Any]", ws.receive_json())
    _check_redaction(frame, seat)
    return frame


def _standard_winning_hand() -> tuple[int, ...]:
    """Same 14-tile shape `tests/test_engine.py::_standard_winning_hand` uses (reproduced
    locally per this repo's per-module fixture convention): 缺一門 + 自摸 + 無花 = 4 faan under
    `DEFAULT_RULESET`'s `min_faan=3` -- clears it comfortably without needing a bigger hand."""
    return (
        *_MAN_1[:3],
        _MAN_4[0],
        _MAN_5[0],
        _MAN_6[0],
        _MAN_7[0],
        _MAN_8[0],
        _MAN_9[0],
        *_PIN_1[:3],
        _MAN_2[0],
        _MAN_2[1],
    )


def _fetch_latest_record(database_url: str) -> GameRecord | None:
    async def _run() -> GameRecord | None:
        engine = make_engine(database_url)
        try:
            factory = make_session_factory(engine)
            async with factory() as session:
                result = await session.execute(select(GameRecord).order_by(GameRecord.id.desc()))
                return result.scalars().first()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_full_game_four_ws_clients_east_only_with_mid_game_reconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "full_game_e2e.db"
    database_url = f"sqlite+aiosqlite:///{db_path}"

    async def _create_schema() -> None:
        engine = make_engine(database_url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

    asyncio.run(_create_schema())
    monkeypatch.setenv("DATABASE_URL", database_url)

    table_id = f"full-game-{uuid.uuid4()}"
    seed = 20260916001

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws0,
        client.websocket_connect(f"/ws?table={table_id}") as ws1,
        client.websocket_connect(f"/ws?table={table_id}") as ws2,
    ):
        table = get_table(table_id)
        assert table is not None

        # --- hand 1 rig: seat 0 dealer, a real claim exchange (matches
        # tests/test_ws_gameplay.py's fixture) ending in exhaustive draw.
        state = new_game(_GAME_RULESET, game_seed=seed)
        state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
        seat0_junk = _tiles(
            TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=13
        )
        seat1_junk = _tiles(TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, count=11)
        seat2_junk = _tiles(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, count=11)
        seat3_junk = _tiles(
            TileType.DRAGON_RED,
            TileType.DRAGON_GREEN,
            TileType.DRAGON_WHITE,
            TileType.WIND_NORTH,
            count=13,
        )
        table.state = _rig_hands(
            state,
            {
                0: (*seat0_junk, _MAN_5[0]),
                1: (_MAN_4[0], _MAN_6[0], *seat1_junk),
                2: (_MAN_5[1], _MAN_5[2], *seat2_junk),
                3: seat3_junk,
            },
        )

        # seat 3's connection is scoped to this nested `with`, ending right after hand 3's
        # `turn` frames land -- stands in for a real mid-hand disconnect.
        with client.websocket_connect(f"/ws?table={table_id}") as ws3:
            wss: list[WebSocketTestSession] = [ws0, ws1, ws2, ws3]
            for ws in wss:
                ws.send_json(_msg("hello", {"client_version": "test"}))

            bound = [False, False, False, False]
            for seat, ws in enumerate(wss):
                ws.send_json(_msg("join", {"seat": seat}, id_=_next_id()))
                bound[seat] = True
                for s, other in enumerate(wss):
                    if bound[s]:
                        assert _recv(other, s)["t"] == "seat_state"
                assert _recv(ws, seat)["t"] == "state_sync"
                assert _recv(ws, seat)["d"]["ok"] is True

            for seat in range(3):
                wss[seat].send_json(_msg("ready", {}, id_=_next_id()))
                assert _recv(wss[seat], seat)["d"]["ok"] is True
            wss[3].send_json(_msg("ready", {}, id_=_next_id()))

            hand_starts = {3: _recv(wss[3], 3)}
            deals = {3: _recv(wss[3], 3)}
            turns = {3: _recv(wss[3], 3)}
            assert _recv(wss[3], 3)["d"]["ok"] is True
            for seat in range(3):
                hand_starts[seat] = _recv(wss[seat], seat)
                deals[seat] = _recv(wss[seat], seat)
                turns[seat] = _recv(wss[seat], seat)

            expected_hands_1 = {
                0: (*seat0_junk, _MAN_5[0]),
                1: (_MAN_4[0], _MAN_6[0], *seat1_junk),
                2: (_MAN_5[1], _MAN_5[2], *seat2_junk),
                3: seat3_junk,
            }
            for seat in range(4):
                assert hand_starts[seat]["t"] == "hand_start"
                assert hand_starts[seat]["d"]["hand_no"] == 1
                assert hand_starts[seat]["d"]["dealer"] == 0
                assert sorted(deals[seat]["d"]["your_hand"]) == sorted(expected_hands_1[seat])
                assert turns[seat]["d"]["seat"] == 0
            assert table.state.hand_seed == derive_hand_seed(seed, 1)

            # --- hand 1 play: seat 0 discards 5m; seat 2's pung beats seat 1's un-answered
            # chow (early exit), seat 2 then discards uncontested -> wall empty -> exh. draw.
            wss[0].send_json(_msg("discard", {"tile_id": _MAN_5[0]}, id_=_next_id()))
            assert _recv(wss[0], 0)["d"]["ok"] is True
            for seat, ws in enumerate(wss):
                assert _recv(ws, seat)["t"] == "discard"
            offer2 = _recv(wss[2], 2)
            assert offer2["t"] == "claim_offer"
            window_id = offer2["d"]["window_id"]
            assert _recv(wss[1], 1)["t"] == "claim_offer"

            wss[2].send_json(
                _msg("claim", {"window_id": window_id, "choice": "pung"}, id_=_next_id())
            )
            assert _recv(wss[2], 2)["d"]["ok"] is True
            for seat, ws in enumerate(wss):
                assert _recv(ws, seat)["t"] == "claim_resolved"
            for seat, ws in enumerate(wss):
                assert _recv(ws, seat)["t"] == "meld"
            post_pung_turn = {seat: _recv(ws, seat) for seat, ws in enumerate(wss)}
            for seat in range(4):
                assert post_pung_turn[seat]["d"]["seat"] == 2
            discard_action = next(
                a for a in post_pung_turn[2]["d"]["legal"] if a["kind"] == "discard"
            )

            wss[2].send_json(
                _msg("discard", {"tile_id": discard_action["tile_id"]}, id_=_next_id())
            )
            assert _recv(wss[2], 2)["d"]["ok"] is True
            expected_types = ["discard", "hand_end", "score", "hand_start", "deal", "turn"]
            frames_h1: dict[int, list[dict[str, Any]]] = {s: [] for s in range(4)}
            for _ in expected_types:
                for seat, ws in enumerate(wss):
                    frames_h1[seat].append(_recv(ws, seat))
            for seat in range(4):
                assert [f["t"] for f in frames_h1[seat]] == expected_types

            hand_end_1 = frames_h1[0][1]["d"]
            assert hand_end_1["outcome"] == "exhaustive_draw"
            assert hand_end_1["hand_no"] == 1
            score_1 = frames_h1[0][2]["d"]
            assert score_1["totals"] == {"0": 0, "1": 0, "2": 0, "3": 0}

            hand_start_2 = frames_h1[0][3]["d"]
            assert hand_start_2["hand_no"] == 2
            assert hand_start_2["dealer"] == 1  # no dealer repeat -> deal passes to seat 1
            assert hand_start_2["prevailing"] == "EAST"
            turn_2 = frames_h1[0][5]["d"]
            assert turn_2["seat"] == 1
            assert table.state.phase == Phase.AWAIT_ACTION
            assert table.state.dealer == 1
            assert table.state.turn == 1
            assert table.state.claim_window is None
            assert table.state.hand_seed == derive_hand_seed(seed, 2)

            # --- hand 2 rig: seat 1 (dealer) self-draw wins immediately on a standard hand.
            seat0_junk_2 = _tiles(
                TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, TileType.SOU_8, count=13
            )
            seat2_junk_2 = _tiles(
                TileType.WIND_EAST,
                TileType.WIND_SOUTH,
                TileType.WIND_WEST,
                TileType.WIND_NORTH,
                count=13,
            )
            seat3_junk_2 = _tiles(
                TileType.DRAGON_RED,
                TileType.DRAGON_GREEN,
                TileType.DRAGON_WHITE,
                TileType.SOU_1,
                count=13,
            )
            rigged_2 = _rig_hands(
                table.state,
                {
                    0: seat0_junk_2,
                    1: _standard_winning_hand(),
                    2: seat2_junk_2,
                    3: seat3_junk_2,
                },
            )
            # total_discards=1: without it, dealer seat 1's turn-1 win scores as Heavenly Hand
            # instead of the 缺一門/自摸/無花 breakdown asserted below (won_before_any_discard).
            table.state = dataclasses.replace(rigged_2, total_discards=1)

            wss[1].send_json(_msg("declare", {"kind": "win"}, id_=_next_id()))
            assert _recv(wss[1], 1)["d"]["ok"] is True
            expected_types_2 = ["hand_end", "score", "hand_start", "deal", "turn"]
            frames_h2: dict[int, list[dict[str, Any]]] = {s: [] for s in range(4)}
            for _ in expected_types_2:
                for seat, ws in enumerate(wss):
                    frames_h2[seat].append(_recv(ws, seat))
            for seat in range(4):
                assert [f["t"] for f in frames_h2[seat]] == expected_types_2
                # win is revealed to every seat identically, not just the winner.
                assert frames_h2[seat][0]["d"]["winning_hand"] is not None
                assert sorted(frames_h2[seat][0]["d"]["winning_hand"]) == sorted(
                    _standard_winning_hand()
                )

            hand_end_2 = frames_h2[0][0]["d"]
            assert hand_end_2["outcome"] == "win"
            assert hand_end_2["winner"] == 1
            assert hand_end_2["win_type"] == "self_draw"
            assert hand_end_2["faan"] == 4
            assert hand_end_2["faan_breakdown"] == {"缺一門": 2, "自摸": 1, "無花": 1}
            score_2 = frames_h2[0][1]["d"]["totals"]
            assert score_2["1"] > 0
            assert score_2["0"] < 0 and score_2["2"] < 0 and score_2["3"] < 0
            assert sum(int(v) for v in score_2.values()) == 0

            hand_start_3 = frames_h2[0][2]["d"]
            assert hand_start_3["hand_no"] == 3
            assert hand_start_3["dealer"] == 2
            assert frames_h2[0][4]["d"]["seat"] == 2
            assert table.state.hand_seed == derive_hand_seed(seed, 3)
            # carried onto the fresh hand 3 state, not reset:
            assert table.state.seats[1].score == int(score_2["1"])

            # hand 3 rig: seat 2 (dealer) discards a tile only seat 3 can chow (no pung
            # available), so the window stays open on seat 3 alone -- needed for the disconnect/reconnect scenario below.
            seat0_junk_3 = _tiles(
                TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=13
            )
            seat1_junk_3 = _tiles(
                TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, TileType.SOU_8, count=13
            )
            seat2_junk_3 = _tiles(
                TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, count=12
            )
            seat3_junk_3 = _tiles(
                TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE, count=11
            )
            assert table.state.phase == Phase.AWAIT_ACTION  # real deal already landed here
            assert table.state.turn == 2
            assert table.state.dealer == 2
            table.state = _rig_hands(
                table.state,
                {
                    0: seat0_junk_3,
                    1: seat1_junk_3,
                    2: (*seat2_junk_3, _MAN_5[0]),
                    3: (_MAN_4[0], _MAN_6[0], *seat3_junk_3),
                },
            )

            # hand 3's hand_start/deal/turn frames were already consumed above (frames_h2[2:5]);
            # this rig only swaps concealed tiles/wall in, it doesn't replay the deal.
            seat3_last_seq = frames_h2[3][4]["seq"]

        # seat 3 disconnects for real, before seat 2's discard -- everything until reconnect
        # (disconnect broadcast, discard, claim_offer) is genuinely missed, not re-armed.
        disc_seat3 = _recv(ws0, 0)
        assert disc_seat3["t"] == "seat_state"
        assert disc_seat3["d"] == {"seat": 3, "status": "disconnected", "name": "Guest 4"}
        assert _recv(ws1, 1)["t"] == "seat_state"
        assert _recv(ws2, 2)["t"] == "seat_state"

        ws2.send_json(_msg("discard", {"tile_id": _MAN_5[0]}, id_=_next_id()))
        assert _recv(ws2, 2)["d"]["ok"] is True
        for seat, ws in ((0, ws0), (1, ws1), (2, ws2)):
            assert _recv(ws, seat)["t"] == "discard"
        # only seat 3 holds a claim option (rig above); re-fetch window_id off Table's own
        # state instead of reading a 4th frame off a bystander connection.

        table = get_table(table_id)
        assert table is not None
        window = table.state.claim_window
        assert window is not None and len(window.offers) == 1 and window.offers[0].seat == 3
        window_id_3 = window.window_id
        seat3_binding = table.seat_bindings[3]
        assert seat3_binding is not None
        seat3_secret = seat3_binding.reconnect_secret

        with client.websocket_connect(f"/ws?table={table_id}") as ws3b:
            ws3b.send_json(
                _msg(
                    "hello",
                    {
                        "client_version": "test",
                        "seat": 3,
                        "last_seq": seat3_last_seq,
                        "secret": seat3_secret,
                    },
                )
            )

            missed_disconnect = _recv(ws3b, 3)
            assert missed_disconnect["t"] == "seat_state"
            assert missed_disconnect["d"] == {
                "seat": 3,
                "status": "disconnected",
                "name": "Guest 4",
            }
            missed_discard = _recv(ws3b, 3)
            assert missed_discard["t"] == "discard"
            assert missed_discard["d"]["tile_id"] == _MAN_5[0]
            missed_offer = _recv(ws3b, 3)
            assert missed_offer["t"] == "claim_offer"
            assert missed_offer["d"]["window_id"] == window_id_3
            original_deadline = missed_offer["d"]["deadline_ts"]

            reconnected = _recv(ws3b, 3)
            assert reconnected["t"] == "seat_state"
            assert reconnected["d"] == {"seat": 3, "status": "connected", "name": "Guest 4"}
            # the reconnect announcement broadcasts to every seat, not just the one that
            # reconnected -- drain it off the three still-live bystander connections too.
            for seat, ws in ((0, ws0), (1, ws1), (2, ws2)):
                frame = _recv(ws, seat)
                assert frame["t"] == "seat_state"
                assert frame["d"] == {"seat": 3, "status": "connected", "name": "Guest 4"}

            rearmed_offer = _recv(ws3b, 3)
            assert rearmed_offer["t"] == "claim_offer"
            assert rearmed_offer["d"]["window_id"] == window_id_3
            assert rearmed_offer["d"]["deadline_ts"] >= original_deadline

            # seat 3 answers for real (genuine Pass, not synthesized timeout) -> window
            # resolves unclaimed -> seat 3 draws into an empty wall -> exhaustive draw.
            ws3b.send_json(
                _msg("claim", {"window_id": window_id_3, "choice": "pass"}, id_=_next_id())
            )
            assert _recv(ws3b, 3)["d"]["ok"] is True

            expected_types_3 = ["claim_resolved", "hand_end", "score", "hand_start", "deal", "turn"]
            frames_h3: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
            live: dict[int, WebSocketTestSession] = {0: ws0, 1: ws1, 2: ws2, 3: ws3b}
            for _ in expected_types_3:
                for seat, ws in live.items():
                    frames_h3[seat].append(_recv(ws, seat))
            for seat in range(4):
                assert [f["t"] for f in frames_h3[seat]] == expected_types_3

            hand_end_3 = frames_h3[0][1]["d"]
            assert hand_end_3["outcome"] == "exhaustive_draw"
            assert hand_end_3["hand_no"] == 3
            hand_start_4 = frames_h3[0][3]["d"]
            assert hand_start_4["hand_no"] == 4
            assert hand_start_4["dealer"] == 3
            assert frames_h3[0][5]["d"]["seat"] == 3
            assert table.state.hand_seed == derive_hand_seed(seed, 4)

            score_after_h3 = frames_h3[0][2]["d"]["totals"]

            # hand 4 rig: final hand of EAST_ONLY (dealer 3) -- one uncontested discard drives
            # straight to Phase.GAME_OVER.
            seat0_junk_4 = _tiles(
                TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=13
            )
            seat1_junk_4 = _tiles(
                TileType.SOU_1, TileType.SOU_3, TileType.SOU_5, TileType.SOU_7, count=13
            )
            seat2_junk_4 = _tiles(
                TileType.WIND_SOUTH,
                TileType.WIND_WEST,
                TileType.WIND_NORTH,
                TileType.DRAGON_RED,
                count=13,
            )
            seat3_discard = tile_ids_for_type(TileType.MAN_1)[0]
            seat3_junk_4 = _tiles(
                TileType.DRAGON_GREEN, TileType.DRAGON_WHITE, TileType.MAN_2, count=12
            )
            assert table.state.dealer == 3
            assert table.state.turn == 3
            table.state = _rig_hands(
                table.state,
                {
                    0: seat0_junk_4,
                    1: seat1_junk_4,
                    2: seat2_junk_4,
                    3: (*seat3_junk_4, seat3_discard),
                },
            )

            live[3] = ws3b
            ws3b.send_json(_msg("discard", {"tile_id": seat3_discard}, id_=_next_id()))
            assert _recv(ws3b, 3)["d"]["ok"] is True

            expected_types_4 = ["discard", "hand_end", "score", "game_end"]
            frames_h4: dict[int, list[dict[str, Any]]] = {0: [], 1: [], 2: [], 3: []}
            for _ in expected_types_4:
                for seat, ws in live.items():
                    frames_h4[seat].append(_recv(ws, seat))
            for seat in range(4):
                assert [f["t"] for f in frames_h4[seat]] == expected_types_4

            hand_end_4 = frames_h4[0][1]["d"]
            assert hand_end_4["outcome"] == "exhaustive_draw"
            assert hand_end_4["hand_no"] == 4
            score_after_h4 = frames_h4[0][2]["d"]["totals"]
            assert score_after_h4 == score_after_h3  # exhaustive draw pays nothing further

            game_end = frames_h4[0][3]["d"]
            assert game_end["hand_no"] == 4
            assert list(game_end["scores"]) == [int(score_after_h4[str(s)]) for s in range(4)]

            assert table.state.phase == Phase.GAME_OVER

        # table.actions = real Action submissions across 4 hands: h1(3) + h2(1) + h3(2) + h4(1)
        # = 7 -- no drift/gap/duplication from the 3 hand boundaries or the mid-h3 disconnect.
        assert len(table.actions) == 7

    record = _fetch_latest_record(database_url)
    assert record is not None
    assert record.engine_version == ENGINE_VERSION
    assert record.seed == seed
    assert RuleSet.from_dict(record.ruleset) == _GAME_RULESET
    assert record.result["hand_count"] == table.state.hand_no == 4
    assert record.result["final_scores"] == [s.score for s in table.state.seats]
    assert sum(record.result["final_scores"]) == 0
    assert len(record.action_log) == len(table.actions) == 7
    assert [action_from_dict(d) for d in record.action_log] == table.actions
