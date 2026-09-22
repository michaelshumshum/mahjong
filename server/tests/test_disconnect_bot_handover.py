"""Disconnect -> bot handover (docs/00-architecture.md §8 "Player disconnects", §3 D12;
docs/05-roadmap.md M3 sub-task 6) -- driven over real WebSocket connections, same
`fastapi.testclient` style `tests/test_ws_gameplay.py`/`tests/test_reconnect.py` established.

`disconnect_grace_seconds=0` is this file's test-time-control pattern for the grace timer --
the same idea `tests/test_table_claims.py`'s `claim_seconds=0` already uses for claim-window
timeouts: the deadline is due the instant it's armed, so the table's own background task pops it
on its very next tick with no real sleep in the test. `Table._wake()` (see `app/table.py`'s
`_WakeUp` docstring) is what makes that pop happen promptly rather than waiting on an unrelated
event to nudge the loop.

Fixture: seat 0 holds a lone, uncontested `WIND_EAST` plus junk (`PIN_2/4/6/8`) -- same shape
`tests/test_reconnect.py`'s `_rig_uncontested_state` uses. Seat 1 (the seat that disconnects)
holds 13 *distinct* singleton tiles (6 honors nobody else holds, plus `MAN_1..MAN_7`), drawing a
14th distinct tile (`MAN_9`) after seat 0's discard -- no duplicate anywhere in its own hand, so
`legal_actions` is pure `Discard`, nothing else (no pair/triple to kong, no win shape). Seats 2
and 3 hold their own disjoint tile types (`SOU_1/3/5/7`, `PIN_1/3/5/7`) with no numeric adjacency
to seat 1's tiles, so *every* possible discard seat 1 (bot or human) could make is guaranteed
uncontested regardless of which one gets picked -- the test doesn't need to know or constrain
which tile the bot chooses, only that the game keeps moving.
"""

from __future__ import annotations

import dataclasses
import itertools
import time
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

_id_gen = itertools.count(1)


def _ts() -> int:
    return time.time_ns() // 1_000_000


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": _ts(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def _next_id() -> str:
    return f"c-{next(_id_gen)}"


def _hello(
    *, last_seq: int | None = None, seat: int | None = None, secret: str | None = None
) -> dict[str, object]:
    d: dict[str, object] = {"client_version": "test"}
    if last_seq is not None:
        d["last_seq"] = last_seq
    if seat is not None:
        d["seat"] = seat
    if secret is not None:
        d["secret"] = secret
    return _msg("hello", d)


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _tiles(*types: TileType, count: int) -> tuple[int, ...]:
    ids = [tid for t in types for tid in tile_ids_for_type(t)]
    return tuple(ids[:count])


def _join_and_ready_all(wss: list) -> dict[int, str]:  # type: ignore[type-arg]
    """Join all four seats (seat i on connection i) and ready them up -- same choreography
    `tests/test_reconnect.py`'s helper of the same name established, minus its `last_seq`
    bookkeeping (this file never needs a gap-replay `last_seq`). Returns each seat's
    `reconnect_secret` from its own `join` ack (00-architecture.md §2.1), needed by this file's
    own `_hello(seat=..., secret=...)` reconnect."""
    for ws in wss:
        ws.send_json(_hello())
    bound = [False, False, False, False]
    secret: dict[int, str] = {}
    for seat, ws in enumerate(wss):
        ws.send_json(_msg("join", {"seat": seat}, id_=_next_id()))
        bound[seat] = True
        for s, other in enumerate(wss):
            if bound[s]:
                frame = other.receive_json()
                assert frame["t"] == "seat_state"
        sync = ws.receive_json()
        assert sync["t"] == "state_sync"
        ack = ws.receive_json()
        assert ack["t"] == "ack"
        secret[seat] = ack["d"]["reconnect_secret"]

    for seat in range(3):
        wss[seat].send_json(_msg("ready", {}, id_=_next_id()))
        ack = wss[seat].receive_json()
        assert ack["t"] == "ack"

    wss[3].send_json(_msg("ready", {}, id_=_next_id()))
    for seat in range(4):
        hand_start = wss[seat].receive_json()
        assert hand_start["t"] == "hand_start"
        deal = wss[seat].receive_json()
        assert deal["t"] == "deal"
        turn = wss[seat].receive_json()
        assert turn["t"] == "turn"
    ack3 = wss[3].receive_json()
    assert ack3["t"] == "ack"
    return secret


def _rig_disconnect_state(seed: int) -> GameState:
    """See module docstring for the tile-partitioning rationale. `disconnect_grace_seconds=0`
    on the ruleset is this fixture's test-time-control knob for the grace timer."""
    ruleset = dataclasses.replace(DEFAULT_RULESET, disconnect_grace_seconds=0)
    state = new_game(ruleset, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)

    seat0 = (
        *_tiles(TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=12),
        tile_ids_for_type(TileType.WIND_EAST)[0],
    )
    seat1 = (
        tile_ids_for_type(TileType.WIND_SOUTH)[0],
        tile_ids_for_type(TileType.WIND_WEST)[0],
        tile_ids_for_type(TileType.WIND_NORTH)[0],
        tile_ids_for_type(TileType.DRAGON_RED)[0],
        tile_ids_for_type(TileType.DRAGON_GREEN)[0],
        tile_ids_for_type(TileType.DRAGON_WHITE)[0],
        # one tile each, not `_tiles(..., count=7)`: that slices the *flattened* id list (all 4
        # copies of the first type before touching the second), not one-per-type -- the wrong
        # shape here, since this hand needs 7 genuinely distinct types with a single copy each.
        tile_ids_for_type(TileType.MAN_1)[0],
        tile_ids_for_type(TileType.MAN_2)[0],
        tile_ids_for_type(TileType.MAN_3)[0],
        tile_ids_for_type(TileType.MAN_4)[0],
        tile_ids_for_type(TileType.MAN_5)[0],
        tile_ids_for_type(TileType.MAN_6)[0],
        tile_ids_for_type(TileType.MAN_7)[0],
    )
    seat2 = _tiles(TileType.SOU_1, TileType.SOU_3, TileType.SOU_5, TileType.SOU_7, count=13)
    seat3 = _tiles(TileType.PIN_1, TileType.PIN_3, TileType.PIN_5, TileType.PIN_7, count=13)

    state = _with_seat(state, 0, concealed=seat0, discards=())
    state = _with_seat(state, 1, concealed=seat1)
    state = _with_seat(state, 2, concealed=seat2)
    state = _with_seat(state, 3, concealed=seat3)

    # seat 1's forced draw (after seat 0's discard) is a 14th distinct type -- no pair, no kong,
    # no win shape; a plain suited tile, not a flower (no extra flower_replace/draw pair).
    draw_tile = tile_ids_for_type(TileType.MAN_9)[0]
    wall = state.wall
    state = dataclasses.replace(
        state, wall=dataclasses.replace(wall, tiles=(draw_tile, *wall.tiles[1:]))
    )
    return state


def test_disconnect_grace_expiry_bot_moves_game_then_reconnect_returns_control() -> None:
    table_id = f"disconnect-handover-{uuid.uuid4()}"

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws0,
        client.websocket_connect(f"/ws?table={table_id}") as ws2,
        client.websocket_connect(f"/ws?table={table_id}") as ws3,
    ):
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_disconnect_state(seed=1)

        with client.websocket_connect(f"/ws?table={table_id}") as ws1:
            secret = _join_and_ready_all([ws0, ws1, ws2, ws3])
            seat1_secret = secret[1]
        # ws1's `with` block just exited -- only seat 1 disconnects; ws0/ws2/ws3 stay live.

        observers = (ws0, ws2, ws3)

        # --- disconnect detection: every other seat sees exactly seat_state{1, disconnected},
        # nothing more (no tile identity, no extra fields -- protocol.py's SeatStatePayload
        # forbids them anyway, but the exact-equality check below proves it at the wire too).
        for ws in observers:
            frame = ws.receive_json()
            assert frame["t"] == "seat_state"
            assert frame["d"] == {"seat": 1, "status": "disconnected", "name": "Guest 2"}
        assert table.seat_bindings[1] is not None

        # --- grace period (0s, already due): the table's own background task pops the timer
        # with no real sleep here -- receive_json() just blocks until it does.
        for ws in observers:
            frame = ws.receive_json()
            assert frame["t"] == "seat_state"
            assert frame["d"] == {"seat": 1, "status": "autoplay", "name": "Guest 2"}
        assert table.seat_bindings[1].status == "autoplay"

        # --- seat 0 discards its uncontested tile -> cascades straight to seat 1's draw+turn
        # (claim-proof by construction, module docstring).
        discard_tile = tile_ids_for_type(TileType.WIND_EAST)[0]
        ws0.send_json(_msg("discard", {"tile_id": discard_tile}, id_=_next_id()))
        ack = ws0.receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True

        for ws in observers:
            discard0 = ws.receive_json()
            assert discard0["t"] == "discard" and discard0["d"]["seat"] == 0
            draw1 = ws.receive_json()
            assert draw1["t"] == "draw" and draw1["d"]["seat"] == 1
            assert draw1["d"]["tile_id"] is None  # redacted -- ws is never seat 1's own stream
            turn1 = ws.receive_json()
            assert turn1["t"] == "turn" and turn1["d"]["seat"] == 1
            assert "legal" not in turn1["d"]  # unicast-only, and nobody here is seat 1

        # --- the bot acts for seat 1 (D12: submitted to a ProcessPoolExecutor, off the table's
        # own asyncio task) -- a real, legal discard arrives with no human involvement, and the
        # game keeps progressing straight into seat 2's draw+turn. This is the "doesn't stall"
        # proof: these receive_json() calls block until the worker round-trip actually lands.
        for ws in observers:
            bot_discard = ws.receive_json()
            assert bot_discard["t"] == "discard"
            assert bot_discard["d"]["seat"] == 1
            draw2 = ws.receive_json()
            assert draw2["t"] == "draw" and draw2["d"]["seat"] == 2
            turn2 = ws.receive_json()
            assert turn2["t"] == "turn" and turn2["d"]["seat"] == 2

        assert table.seat_bindings[1].status == "autoplay"
        assert 1 not in table._pending_bot  # the job resolved and was cleared, not left hanging

        # --- reconnect: status flips back, the bot stops acting for the seat (D12 staleness
        # drop doubling as "stop", app/table.py's reconnect() docstring).
        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            ws1b.send_json(_hello(seat=1, secret=seat1_secret))

            for ws in observers:
                frame = ws.receive_json()
                assert frame["t"] == "seat_state"
                assert frame["d"] == {"seat": 1, "status": "connected", "name": "Guest 2"}

            # mypy narrows this status to Literal["autoplay"] from the assert at line 194 and
            # doesn't see the reconnect handling above (driven through real websocket frames)
            # flip it back -- flags this as non-overlapping/unreachable, but it's real and correct.
            assert table.seat_bindings[1].status == "connected"
            assert 1 not in table._pending_bot


def _rig_faan_discard_state(seed: int) -> GameState:
    """Seat 1 holds a hand that's already tenpai (shanten 0) *before* drawing one junk honor:
    three complete MAN runs (`MAN_1..9`), a PIN pair, and a SOU kanchan (`SOU_4`/`SOU_6`,
    waiting on `SOU_5`) -- 13 tiles, uniquely decomposable (disjoint suits, no alternate parse).
    Drawing `WIND_EAST` (a 14th, otherwise-irrelevant type) and discarding it is the *unique*
    shanten-minimising choice: discarding anything else breaks the run/pair/kanchan structure
    and raises shanten from 0 to 1 (checked by hand against `mahjong_core.shanten`'s formula --
    `melds=3, partials=1, has_pair=1` gives `shanten=(4-3)*2-1-1=0`; removing one tile from any
    of those three blocks instead drops a meld or the pair/partial, giving `shanten=1` under the
    same formula, every time). At turn 0 (seat 1's very first discard this hand),
    `bots/faanbot.py`'s `_weights_for_turn` sets `w_speed=1.0`, so the resulting
    `_SHANTEN_UNIT=5.0` gap between keeping vs. breaking tenpai dwarfs any value/safety/flex
    delta among the 13 legal discards -- both T1 (`EfficiencyBot`, which minimises shanten
    unconditionally) and T2 (`FaanBot`) discard `WIND_EAST` deterministically. `RandomBot` (T0)
    would instead pick uniformly among the 13 legal discard ids. Every other seat's tiles are
    disjoint from seat 1's and from `WIND_EAST`/`DRAGON_RED` (seat 0's own uncontested discard,
    below), so neither discard this fixture actually exercises opens a claim window.
    """
    ruleset = dataclasses.replace(DEFAULT_RULESET, disconnect_grace_seconds=0)
    state = new_game(ruleset, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)

    seat0 = (
        *_tiles(TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=12),
        tile_ids_for_type(TileType.DRAGON_RED)[0],
    )
    seat1 = (
        tile_ids_for_type(TileType.MAN_1)[0],
        tile_ids_for_type(TileType.MAN_2)[0],
        tile_ids_for_type(TileType.MAN_3)[0],
        tile_ids_for_type(TileType.MAN_4)[0],
        tile_ids_for_type(TileType.MAN_5)[0],
        tile_ids_for_type(TileType.MAN_6)[0],
        tile_ids_for_type(TileType.MAN_7)[0],
        tile_ids_for_type(TileType.MAN_8)[0],
        tile_ids_for_type(TileType.MAN_9)[0],
        tile_ids_for_type(TileType.PIN_2)[0],
        tile_ids_for_type(TileType.PIN_2)[1],
        tile_ids_for_type(TileType.SOU_4)[0],
        tile_ids_for_type(TileType.SOU_6)[0],
    )
    seat2 = _tiles(TileType.SOU_1, TileType.SOU_3, TileType.SOU_5, TileType.SOU_7, count=13)
    seat3 = _tiles(TileType.PIN_1, TileType.PIN_3, TileType.PIN_5, TileType.PIN_7, count=13)

    state = _with_seat(state, 0, concealed=seat0, discards=())
    state = _with_seat(state, 1, concealed=seat1)
    state = _with_seat(state, 2, concealed=seat2)
    state = _with_seat(state, 3, concealed=seat3)

    draw_tile = tile_ids_for_type(TileType.WIND_EAST)[0]
    wall = state.wall
    state = dataclasses.replace(
        state, wall=dataclasses.replace(wall, tiles=(draw_tile, *wall.tiles[1:]))
    )
    return state


def test_disconnect_bot_runs_faanbot_not_random() -> None:
    """Regression for the sub-task that wired real bot tiers into the live disconnect-handover
    path (docs/04-bots.md §1, docs/05-roadmap.md M4.5): `Table`'s default `bot_tier` is now
    `T2`/`FaanBot`, not the old hardcoded `T0`/`RandomBot` `bots/worker.py.compute_action` used
    to run unconditionally. `_rig_faan_discard_state`'s hand has a *unique* shanten-minimising
    discard (see its own docstring); `FaanBot`'s choice is a deterministic function of the hand
    (unlike `RandomBot`'s uniform-over-13 pick), so asserting the exact discard tile is a real
    proof the live path is no longer T0 -- not merely improbable-under-random, but exactly what
    a value/efficiency-aware policy must produce here, every run.
    """
    table_id = f"disconnect-handover-faanbot-{uuid.uuid4()}"

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws0,
        client.websocket_connect(f"/ws?table={table_id}") as ws2,
        client.websocket_connect(f"/ws?table={table_id}") as ws3,
    ):
        table = get_table(table_id)
        assert table is not None
        assert table._bot_tier == "T2"  # the M4.5 default -- FaanBot, not RandomBot
        table.state = _rig_faan_discard_state(seed=2)

        with client.websocket_connect(f"/ws?table={table_id}") as ws1:
            _join_and_ready_all([ws0, ws1, ws2, ws3])
        # ws1's `with` block just exited -- only seat 1 disconnects.

        observers = (ws0, ws2, ws3)

        for ws in observers:
            frame = ws.receive_json()
            assert frame["t"] == "seat_state"
            assert frame["d"] == {"seat": 1, "status": "disconnected", "name": "Guest 2"}

        for ws in observers:
            frame = ws.receive_json()
            assert frame["t"] == "seat_state"
            assert frame["d"] == {"seat": 1, "status": "autoplay", "name": "Guest 2"}

        discard_tile = tile_ids_for_type(TileType.DRAGON_RED)[0]
        ws0.send_json(_msg("discard", {"tile_id": discard_tile}, id_=_next_id()))
        ack = ws0.receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True

        for ws in observers:
            discard0 = ws.receive_json()
            assert discard0["t"] == "discard" and discard0["d"]["seat"] == 0
            draw1 = ws.receive_json()
            assert draw1["t"] == "draw" and draw1["d"]["seat"] == 1
            turn1 = ws.receive_json()
            assert turn1["t"] == "turn" and turn1["d"]["seat"] == 1

        expected_tile = tile_ids_for_type(TileType.WIND_EAST)[0]
        for ws in observers:
            bot_discard = ws.receive_json()
            assert bot_discard["t"] == "discard"
            assert bot_discard["d"]["seat"] == 1
            # the unique shanten-minimising choice (fixture docstring) -- a uniform-random T0
            # policy would only land here by ~1/13 chance; a deterministic value/efficiency
            # policy lands here every run.
            assert bot_discard["d"]["tile_id"] == expected_tile
