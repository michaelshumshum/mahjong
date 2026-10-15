"""Reconnect/resync from `last_seq` (docs/protocol.md §5, docs/architecture.md §8;
docs/decisions/0018-milestone-plan.md M3 sub-task 5) -- M3's literal done-when gate: "killing one mid-hand and
reconnecting resumes correctly from last_seq".

Each scenario drives a real `Table` over real WebSocket connections
(`fastapi.testclient`, same style `tests/test_ws_gameplay.py` established): a seat's connection
is closed to simulate a disconnect (its `SeatBinding` -- idempotency cache, ready flag, ring
buffer -- survives that; only the live-socket half is gone, protocol.md §1/§5), fresh events
are driven through the table while that seat has no live socket, then a new connection re-`hello`s
with `seat` + `last_seq` and the result is checked against what was actually missed. Timer-heap
assertions read `Table`'s private per-seat tracking dicts directly, the same white-box style
`tests/test_table_claims.py` already uses on `table.deadlines`/`_armed_window_id`.

**A real, CI-only race lived in this white-box style -- fixed, not previously documented.**
`starlette.testclient.TestClient` runs the ASGI app's event loop on its own OS thread (an
`anyio` `BlockingPortal`); this module's test thread only ever talks to it through
`WebSocketTestSession.send`/`receive`, both `portal.call(...)` round trips. `send` (used by
this file's `ws.send_json(...)` helper calls) is fire-and-forget from the *test's* point of
view: it hands the frame to the app's incoming `anyio` stream and returns as soon as that
handoff itself completes -- it does not wait for the app's own `ws_endpoint` loop, running on
the portal's thread, to actually dequeue the frame, dispatch it through `Session.handle`, and
run whatever `Table` method (`reconnect`/`resume`/...) that entails. `receive`, by contrast,
genuinely blocks until the app produces a frame, which -- since `Table.reconnect`/`Table.resume`
have no `await` anywhere in them, see `resume`'s own docstring -- can only happen *after* that
handler has already run to completion, rearms and all.

Two scenarios below used to assert directly against `Table`'s own attributes (`seat_seq`,
`ring`, `_active_seat_timer`, `_claim_deadline_ms`) immediately after a `hello` `send_json`,
with no `receive_json` in between -- nothing here actually waited for the server's own
event-loop thread to have processed that `hello` yet, so the assertion was racing it. On this
repo's own fast, idle dev machine the event loop (blocked on nothing else) almost always won
that race well before the next Python bytecode on the test thread ran; on a loaded/shared CI
runner, thread-scheduling latency was occasionally large enough for the test thread to read
Table's pre-reconnect state instead, failing an assertion that was, a moment later, actually
true. Every other scenario in this file already happened to have a real `receive_json` between
the `hello` send and its own direct-state assertions (forcing the same synchronization as a
side effect) -- purely by how each was written, not by design -- which is why only these two
ever flaked, and only ever on CI. Fix: order every direct `Table`-state assertion after at least
one `receive_json` produced by that same `hello`'s handling, never before.
"""

from __future__ import annotations

import dataclasses
import itertools
import uuid
from collections import deque

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.clock import now_ms
from app.main import app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type

_id_gen = itertools.count(1)


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": now_ms(), "d": d}
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


def _join_and_ready_all(wss: list) -> tuple[dict[int, int], dict[int, str]]:  # type: ignore[type-arg]
    """Join all four seats (seat i on connection i) and ready them up -- same choreography
    tests/test_ws_gameplay.py established, minus its content assertions (these tests only care
    about what happens *after* a disconnect/reconnect). Returns each seat's own last-seen `seq`,
    read straight off the frames actually received rather than hand-derived, so later
    `last_seq=` values in this file are always exactly what that connection really has -- plus
    each seat's `reconnect_secret` from its own `join` ack (architecture.md §2.1), needed by
    any later `_hello(seat=..., secret=...)` reconnect in this file."""
    for ws in wss:
        ws.send_json(_hello())
    bound = [False, False, False, False]
    last_seq: dict[int, int] = {}
    secret: dict[int, str] = {}
    for seat, ws in enumerate(wss):
        ws.send_json(_msg("join", {"seat": seat}, id_=_next_id()))
        bound[seat] = True
        for s, other in enumerate(wss):
            if bound[s]:
                frame = other.receive_json()
                assert frame["t"] == "seat_state"
                last_seq[s] = frame["seq"]
        sync = ws.receive_json()
        assert sync["t"] == "state_sync"
        last_seq[seat] = sync["seq"]
        ack = ws.receive_json()
        assert ack["t"] == "ack"
        last_seq[seat] = ack["seq"]
        secret[seat] = ack["d"]["reconnect_secret"]

    for seat in range(3):
        wss[seat].send_json(_msg("ready", {}, id_=_next_id()))
        ack = wss[seat].receive_json()
        assert ack["t"] == "ack"
        last_seq[seat] = ack["seq"]

    wss[3].send_json(_msg("ready", {}, id_=_next_id()))
    for seat in range(4):
        hand_start = wss[seat].receive_json()
        assert hand_start["t"] == "hand_start"
        deal = wss[seat].receive_json()
        assert deal["t"] == "deal"
        turn = wss[seat].receive_json()
        assert turn["t"] == "turn"
        last_seq[seat] = turn["seq"]
    ack3 = wss[3].receive_json()
    assert ack3["t"] == "ack"
    last_seq[3] = ack3["seq"]
    return last_seq, secret


def _drain_teardown_disconnects(
    ws: WebSocketTestSession, seats: tuple[int, ...] = (3, 2, 1)
) -> None:
    """Every scenario below closes `ws1`/`ws2`/`ws3` together in one `with (... as ws1, ... as
    ws2, ... as ws3):` block (M3 sub-task 6: a closed WS connection now marks its seat
    `disconnected` and broadcasts `seat_state`) -- multiple context managers in one `with` exit
    in reverse declaration order, so seat 3 disconnects first, then 2, then 1. `ws` is any
    connection still open to observe the broadcasts (every scenario here keeps `ws0` open
    throughout)."""
    for seat in seats:
        frame = ws.receive_json()
        assert frame["t"] == "seat_state"
        assert frame["d"] == {"seat": seat, "status": "disconnected", "name": f"Guest {seat + 1}"}


def _rig_uncontested_state(seed: int) -> GameState:
    """Seat 0 on turn holding a lone East wind plus junk; no other seat holds any East wind at
    all (chow is structurally impossible for an honor tile, and pung needs 2+ copies), so
    discarding it is guaranteed uncontested -- cascades straight through `draw`+`turn` for seat
    1 with no claim window in the way."""
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    seat0 = (
        *_tiles(TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=12),
        tile_ids_for_type(TileType.WIND_EAST)[0],
    )
    seat1 = _tiles(TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, TileType.SOU_8, count=13)
    seat2 = _tiles(
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_WHITE,
        TileType.WIND_SOUTH,
        count=13,
    )
    seat3 = _tiles(
        TileType.WIND_WEST, TileType.WIND_NORTH, TileType.PIN_1, TileType.PIN_3, count=13
    )
    state = _with_seat(state, 0, concealed=seat0, discards=())
    state = _with_seat(state, 1, concealed=seat1)
    state = _with_seat(state, 2, concealed=seat2)
    state = _with_seat(state, 3, concealed=seat3)
    # force seat 1's next draw to a plain suited tile, not a flower -- avoids an extra
    # flower_replace/draw pair this fixture doesn't need to model.
    safe_tile = tile_ids_for_type(TileType.PIN_5)[0]
    wall = state.wall
    state = dataclasses.replace(
        state, wall=dataclasses.replace(wall, tiles=(safe_tile, *wall.tiles[1:]))
    )
    return state


def _rig_claim_window_state(seed: int) -> GameState:
    """Seat 0 on turn holding 5m plus junk; seat 1 can chow it (4m/6m), seat 2 can pung it (two
    more 5m), seat 3 holds nothing relevant -- same shape tests/test_table_claims.py's fixture
    uses, reproduced locally (each test module here owns its own fixtures)."""
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    man4 = tile_ids_for_type(TileType.MAN_4)
    man5 = tile_ids_for_type(TileType.MAN_5)
    man6 = tile_ids_for_type(TileType.MAN_6)
    seat0_junk = _tiles(TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=12)
    seat1_junk = _tiles(TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, count=11)
    seat2_junk = _tiles(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, count=11)
    seat3_junk = _tiles(
        TileType.DRAGON_RED,
        TileType.DRAGON_GREEN,
        TileType.DRAGON_WHITE,
        TileType.WIND_NORTH,
        count=13,
    )
    state = _with_seat(state, 0, concealed=(*seat0_junk, man5[0]), discards=())
    state = _with_seat(state, 1, concealed=(man4[0], man6[0], *seat1_junk))
    state = _with_seat(state, 2, concealed=(man5[1], man5[2], *seat2_junk))
    state = _with_seat(state, 3, concealed=seat3_junk)
    return state


def test_reconnect_within_ring_replays_exactly_the_missed_frames_no_more_no_dupes() -> None:
    table_id = f"reconnect-replay-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_uncontested_state(seed=1)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
        ):
            wss = [ws0, ws1, ws2, ws3]
            last_seq, secret = _join_and_ready_all(wss)
            seat1_last_seq = last_seq[1]
            seat1_secret = secret[1]

        # ws1's socket is gone but its SeatBinding survives (what makes reconnect possible);
        # closing ws1/ws2/ws3 together also marks all three `disconnected`, broadcast to ws0.
        _drain_teardown_disconnects(ws0)

        discard_tile = tile_ids_for_type(TileType.WIND_EAST)[0]
        ws0.send_json(_msg("discard", {"tile_id": discard_tile}, id_=_next_id()))
        ack = ws0.receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True
        discard_evt = ws0.receive_json()
        assert discard_evt["t"] == "discard"
        draw_evt = ws0.receive_json()
        assert draw_evt["t"] == "draw"
        turn_evt = ws0.receive_json()
        assert turn_evt["t"] == "turn"

        # exactly 3 frames landed in seat 1's ring while it was offline: discard, draw, turn
        # (further back in the ring: the 3 disconnect `seat_state` broadcasts above).
        missed = list(table.ring[1])[-3:]
        assert [e.event["t"] for e in missed] == ["discard", "draw", "turn"]
        seat_seq_before_resume = table.seat_seq[1]

        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            ws1b.send_json(_hello(seat=1, last_seq=seat1_last_seq, secret=seat1_secret))

            # seat1_last_seq predates the 3 disconnect broadcasts too (captured back in
            # `_join_and_ready_all`, before any of this) -- replay picks those up first.
            _drain_teardown_disconnects(ws1b)

            replayed = [ws1b.receive_json() for _ in missed]
            assert [f["t"] for f in replayed] == ["discard", "draw", "turn"]
            assert [f["seq"] for f in replayed] == [e.seq for e in missed]
            # seat 1's own draw is unicast -- the replayed frame must carry its real tile_id,
            # exactly as originally redacted (never re-redacted against today's state).
            assert replayed[1]["d"]["tile_id"] == missed[1].event["tile_id"]
            assert replayed[2]["d"]["seat"] == 1 and "legal" in replayed[2]["d"]

            # replay itself never allocates a fresh seq -- it resends exactly what's already
            # buffered; the +1 is the live `seat_state{connected}` `resume()` sends afterward.
            assert table.seat_seq[1] == seat_seq_before_resume + 1
            reconnected = ws1b.receive_json()
            assert reconnected["t"] == "seat_state"
            assert reconnected["d"] == {"seat": 1, "status": "connected", "name": "Guest 2"}


def test_reconnect_too_old_falls_back_to_full_state_sync() -> None:
    table_id = f"reconnect-stale-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_uncontested_state(seed=2)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
        ):
            wss = [ws0, ws1, ws2, ws3]
            last_seq, secret = _join_and_ready_all(wss)
            seat1_last_seq = last_seq[1]
            seat1_secret = secret[1]

        _drain_teardown_disconnects(ws0)

        discard_tile = tile_ids_for_type(TileType.WIND_EAST)[0]
        ws0.send_json(_msg("discard", {"tile_id": discard_tile}, id_=_next_id()))
        # ack, discard, draw, turn -- from ws0's own uncontested discard
        ws0.receive_json()
        ws0.receive_json()
        ws0.receive_json()
        ws0.receive_json()

        # simulate ring eviction: `last_seq` (the ready cascade's `turn` frame) is now older
        # than anything left in the ring, exactly what a real 512-frame eviction would produce.
        table.ring[1] = deque((e for e in table.ring[1] if e.seq > seat1_last_seq), maxlen=512)
        assert table.ring[1] and table.ring[1][0].seq > seat1_last_seq

        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            ws1b.send_json(_hello(seat=1, last_seq=seat1_last_seq, secret=seat1_secret))
            frame = ws1b.receive_json()
            assert frame["t"] == "state_sync"
            assert frame["d"]["seat"] == 1
            # `resume()`'s state_sync branch still announces the reconnect afterward.
            reconnected = ws1b.receive_json()
            assert reconnected["t"] == "seat_state"
            assert reconnected["d"] == {"seat": 1, "status": "connected", "name": "Guest 2"}


def test_reconnect_at_head_resumes_live_with_nothing_replayed() -> None:
    table_id = f"reconnect-live-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_uncontested_state(seed=3)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
        ):
            wss = [ws0, ws1, ws2, ws3]
            _, secret = _join_and_ready_all(wss)
            seat1_secret = secret[1]

        # closing ws1/ws2/ws3 pushed seat 1's seq/ring head forward by 3 (one disconnect
        # broadcast each) -- capture last_seq *after* that, not before, matching "at head".
        _drain_teardown_disconnects(ws0)
        seat1_last_seq = table.seat_seq[1] - 1
        seq_before = table.seat_seq[1]
        ring_len_before = len(table.ring[1])

        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            ws1b.send_json(_hello(seat=1, last_seq=seat1_last_seq, secret=seat1_secret))

            # no replay needed, but reconnecting from `disconnected` still bumps seq by one
            # `seat_state` -- receive it before asserting table state directly (`send_json` doesn't guarantee resume() ran yet).
            reconnected = ws1b.receive_json()
            assert reconnected["t"] == "seat_state"
            assert reconnected["d"] == {"seat": 1, "status": "connected", "name": "Guest 2"}
            assert table.seat_seq[1] == seq_before + 1
            assert len(table.ring[1]) == ring_len_before + 1

            # the connection is genuinely live again: a fresh broadcast reaches it with the
            # very next seq, no gap.
            ws0.send_json(
                _msg(
                    "discard", {"tile_id": tile_ids_for_type(TileType.WIND_EAST)[0]}, id_=_next_id()
                )
            )
            live_frame = ws1b.receive_json()
            assert live_frame["t"] == "discard"
            assert live_frame["seq"] == seq_before + 1


def test_disconnect_mid_claim_window_forfeits_immediately_no_rearm_on_reconnect() -> None:
    """Superseded design (`app/table.py`'s `_handle_seat_disconnected` docstring): a seat that
    disconnects while its own claim offer is still live used to just sit there until either it
    reconnected (`Table.resume()`'s `_rearm_seat_claim_timer`, re-arming a fresh full window) or
    the original deadline timed it out to Pass. That re-arm was never actually reachable through
    a full-`state_sync` reconnect (the common case once a page reload persists its own seat,
    docs/frontend.md) -- `StateSyncPayload.claim_options` carries no `window_id`, so the
    client had nothing to render a dialog against or submit a `claim` with, even though the
    server was still nominally waiting on it. Now a disconnect forfeits the offer immediately
    instead, so there's nothing left for any later reconnect to hand back.

    Proving the forfeit already landed *before* any reconnect, without racing the server's own
    event-loop thread (this module's own docstring): seat 1's chow and seat 2's pung are the
    window's only two offers, so it can only resolve once *both* have a response recorded.
    Seat 2 sends a real `Pass` after seat 1 disconnects; seat 1 itself never sends anything at
    all (it's offline). Seeing the window resolve regardless is only possible if seat 1's offer
    was already forfeited -- there's no other way its response could exist."""
    table_id = f"reconnect-claim-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_claim_window_state(seed=4)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
        ):
            wss = [ws0, ws1, ws2, ws3]
            _, secret = _join_and_ready_all(wss)
            seat1_secret = secret[1]

            man5 = tile_ids_for_type(TileType.MAN_5)
            ws0.send_json(_msg("discard", {"tile_id": man5[0]}, id_=_next_id()))
            ws0.receive_json()  # ack
            ws0.receive_json()  # discard, seat 0's own stream

            discard1 = ws1.receive_json()
            assert discard1["t"] == "discard"
            offer1 = ws1.receive_json()
            assert offer1["t"] == "claim_offer"
            window_id = offer1["d"]["window_id"]
            seat1_last_seq = offer1["seq"]

            ws2.receive_json()  # discard
            offer2 = ws2.receive_json()
            assert offer2["t"] == "claim_offer"

            ws1.close()  # seat 1 disconnects with its chow offer still unanswered

            seat1_disconnected = ws2.receive_json()
            assert seat1_disconnected["t"] == "seat_state"
            assert seat1_disconnected["d"] == {
                "seat": 1,
                "status": "disconnected",
                "name": "Guest 2",
            }

            # a real Pass from seat 2 -- the window's other, still-open offer -- with seat 1
            # never sending anything itself (this module's own docstring, above).
            claim_id = _next_id()
            ws2.send_json(_msg("claim", {"window_id": window_id, "choice": "pass"}, id_=claim_id))
            ack = ws2.receive_json()
            assert ack["d"] == {"id": claim_id, "ok": True}

            resolved = ws2.receive_json()
            assert resolved["t"] == "claim_resolved"
            assert resolved["d"] == {
                "window_id": window_id,
                "claim_kind": "discard",
                "seat": None,
                "action_kind": None,
            }
            assert table.state.claim_window is None  # fully resolved, nobody claimed

        # seat 1's claim offer was already forfeited and the window resolved while offline, so
        # no `claim_offer` appears in the replay -- drain until resume()'s reconnect frame (always last) and check.
        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            ws1b.send_json(_hello(seat=1, last_seq=seat1_last_seq, secret=seat1_secret))

            seen_types: list[str] = []
            while True:
                frame = ws1b.receive_json()
                seen_types.append(frame["t"])
                if frame["t"] == "seat_state" and frame["d"] == {
                    "seat": 1,
                    "status": "connected",
                    "name": "Guest 2",
                }:
                    break
            assert "claim_offer" not in seen_types


def test_reconnect_preserves_chosen_name_without_resending_it() -> None:
    """M5 (docs/protocol.md §2/§5): `join.name` is set once and lives on `SeatBinding.name`
    for the rest of the game -- a `hello` reconnect carries only `seat`/`last_seq`, never
    `name`, and the server must still know it (and broadcast it) without a resend."""
    table_id = f"reconnect-name-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None

        with client.websocket_connect(f"/ws?table={table_id}") as ws1:
            ws0.send_json(_hello())
            ws1.send_json(_hello())
            ws0.send_json(_msg("join", {"seat": 0}, id_=_next_id()))
            # seat_state (own join), state_sync, ack
            ws0.receive_json()
            ws0.receive_json()
            ws0.receive_json()

            ws1.send_json(_msg("join", {"seat": 1, "name": "Carol"}, id_=_next_id()))
            joined = ws0.receive_json()  # seat_state broadcast reaches seat 0 live
            assert joined["t"] == "seat_state"
            assert joined["d"] == {"seat": 1, "status": "connected", "name": "Carol"}
            ws1.receive_json()  # seat_state (own join)
            sync1 = ws1.receive_json()
            assert sync1["t"] == "state_sync"
            ack1 = ws1.receive_json()
            assert ack1["t"] == "ack"

            binding = table.seat_bindings[1]
            assert binding is not None
            assert binding.name == "Carol"
            seat1_last_seq = ack1["seq"]
            seat1_secret = ack1["d"]["reconnect_secret"]

        # ws1's `with` block exits -- seat 1 disconnects; seat 0 observes it, name unchanged.
        disconnect = ws0.receive_json()
        assert disconnect["t"] == "seat_state"
        assert disconnect["d"] == {"seat": 1, "status": "disconnected", "name": "Carol"}

        with client.websocket_connect(f"/ws?table={table_id}") as ws1b:
            # reconnect carries no `name` at all -- the server still knows it.
            ws1b.send_json(_hello(seat=1, last_seq=seat1_last_seq, secret=seat1_secret))
            # its own disconnect broadcast landed in its own ring too (same seat, same stream)
            # -- replayed back first, name intact, before the fresh "connected" announcement.
            replayed_disconnect = ws1b.receive_json()
            assert replayed_disconnect["t"] == "seat_state"
            assert replayed_disconnect["d"] == {
                "seat": 1,
                "status": "disconnected",
                "name": "Carol",
            }
            reconnected = ws1b.receive_json()
            assert reconnected["t"] == "seat_state"
            assert reconnected["d"] == {"seat": 1, "status": "connected", "name": "Carol"}

        assert table.seat_bindings[1] is not None
        assert table.seat_bindings[1].name == "Carol"


def test_hello_wrong_or_missing_secret_refuses_the_reclaim() -> None:
    """architecture.md §2.1: a `hello{seat}` naming an already-bound seat must present that
    seat's own `reconnect_secret` (from its `join` ack) back, or the reclaim is refused --
    `error{code:'bad_secret'}` -- rather than silently handing the seat to whoever asks. Covers
    both a wrong secret and an altogether missing one (a stale/never-had-one client)."""
    table_id = f"reconnect-bad-secret-{uuid.uuid4()}"
    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None

        ws0.send_json(_hello())
        ws0.send_json(_msg("join", {"seat": 0}, id_=_next_id()))
        ws0.receive_json()  # seat_state (own join)
        ws0.receive_json()  # state_sync
        ack0 = ws0.receive_json()
        assert ack0["t"] == "ack"
        real_secret = ack0["d"]["reconnect_secret"]
        assert isinstance(real_secret, str) and real_secret

        with client.websocket_connect(f"/ws?table={table_id}") as ws_wrong:
            ws_wrong.send_json(_hello(seat=0, secret="not-the-real-secret"))
            frame = ws_wrong.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "bad_secret"

        with client.websocket_connect(f"/ws?table={table_id}") as ws_missing:
            ws_missing.send_json(_hello(seat=0))
            frame = ws_missing.receive_json()
            assert frame["t"] == "error"
            assert frame["d"]["code"] == "bad_secret"

        # neither bad attempt reclaimed the seat -- the real secret still works, proving
        # reconnect never rebound the connection (ws0 never closed, so resume() sends state_sync).
        with client.websocket_connect(f"/ws?table={table_id}") as ws0b:
            ws0b.send_json(_hello(seat=0, secret=real_secret))
            reconnected = ws0b.receive_json()
            assert reconnected["t"] == "state_sync"
            assert reconnected["d"]["seat"] == 0
