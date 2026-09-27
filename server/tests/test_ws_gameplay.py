"""Real gameplay over the wire (docs/05-roadmap.md M3 sub-task 4) -- the M3 gate in miniature:
four scripted WS clients `join` the same table, `ready` up, and play a hand through real
`discard`/`claim`/`declare` intents, asserting correctly-sequenced, correctly-redacted frames.

The mid-hand fixture (seat 0 discards 5m, seat 1 can chow it, seat 2 can pung it, seat 3 holds
nothing relevant) is `tests/test_table_claims.py`'s exact fixture, injected the same white-box
way that module already established (`table.state = ...`) -- here additionally with an emptied
wall, so the hand ends in a fast, deterministic exhaustive draw right after the pung resolves
and its claimant discards, instead of needing to hand-craft a real winning hand or play out
however much of the wall real random legal actions would need. That still exercises a full
hand boundary (`hand_end`, `score`, and the next hand's `hand_start`/`deal`/`turn`) over the
real wire, not just the claim exchange.

Every read below is a *blocking* `receive_json()` on a specific connection's queue, never a
raw count-mismatch risk: a session's own outbound stream is strictly FIFO in true production
order (`app/table.py`'s `Table.publish_to_seat`), so reading a known, derivable number of frames
off a specific connection can only return exactly those frames in that order -- there is
nothing to race. The one thing to get right is *how many* frames a given step produces per
connection, which is computed here the same way `Table` produces it (a broadcast reaches every
currently-bound seat; a unicast reaches one), not hand-counted.
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

_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)
_MAN_6 = tile_ids_for_type(TileType.MAN_6)


def _tiles(*types: TileType, count: int) -> tuple[int, ...]:
    ids = [tid for t in types for tid in tile_ids_for_type(t)]
    return tuple(ids[:count])


# unlike test_table_claims.py's fixture, this test plays a real second discard, so each seat's
# junk must be physically distinct (no shared tile_id) and type-exclusive (seat 2's eventual discard uses honors, so no other seat can chow or pung it).
_SEAT0_JUNK = _tiles(TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=13)
_SEAT1_JUNK = _tiles(TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, count=11)
_SEAT2_JUNK = _tiles(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, count=11)
_SEAT3_JUNK = _tiles(
    TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE, TileType.WIND_NORTH, count=13
)

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


def _payload(frame: dict[str, object]) -> dict[str, object]:
    data = frame["d"]
    assert isinstance(data, dict)
    return data


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _rig_state(seed: int) -> GameState:
    """Seat 0 on turn holding 5m plus junk; seat 1 can chow the 5m (holds 4m/6m), seat 2 can
    pung it (holds two more 5m), seat 3 holds nothing relevant. Wall emptied so the hand ends
    in exhaustive draw right after the pung's claimant discards a junk tile."""
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = _with_seat(state, 0, concealed=(*_SEAT0_JUNK, _MAN_5[0]), discards=())
    state = _with_seat(state, 1, concealed=(_MAN_4[0], _MAN_6[0], *_SEAT1_JUNK))
    state = _with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_SEAT2_JUNK))
    state = _with_seat(state, 3, concealed=_SEAT3_JUNK)
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


def test_full_hand_over_real_ws_multi_client() -> None:
    table_id = f"gameplay-{uuid.uuid4()}"

    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_state(seed=20260916)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
        ):
            wss = [ws0, ws1, ws2, ws3]
            for ws in wss:
                ws.send_json(_msg("hello", {"client_version": "test"}))

            # --- join: each join broadcasts seat_state to every already-bound seat (this one
            # included), then unicasts state_sync + ack to the joiner only.
            bound = [False, False, False, False]
            for seat, ws in enumerate(wss):
                ws.send_json(_msg("join", {"seat": seat}, id_=_next_id()))
                bound[seat] = True
                for s, other in enumerate(wss):
                    if bound[s]:
                        frame = other.receive_json()
                        assert frame["t"] == "seat_state"
                        assert frame["d"] == {
                            "seat": seat,
                            "status": "connected",
                            "name": f"Guest {seat + 1}",
                        }
                sync = ws.receive_json()
                assert sync["t"] == "state_sync"
                assert sync["d"]["seat"] == seat
                ack = ws.receive_json()
                assert ack["t"] == "ack"
                assert ack["d"]["ok"] is True

            # redaction spot-check on join's own state_sync: each seat sees only its own tiles.
            # (seat 0's sync above already reflects the rig -- rigged before any ready fired.)

            # --- ready: each ack fires immediately; the 4th also cascades hand_start/deal/turn
            # to every seat (dealing gates on all-four-ready, 02-protocol.md §2).
            for seat in range(3):
                wss[seat].send_json(_msg("ready", {}, id_=_next_id()))
                ack = wss[seat].receive_json()
                assert ack["t"] == "ack" and ack["d"]["ok"] is True

            wss[3].send_json(_msg("ready", {}, id_=_next_id()))
            hand_start_3 = wss[3].receive_json()
            deal_3 = wss[3].receive_json()
            turn_3 = wss[3].receive_json()
            ack_3 = wss[3].receive_json()
            assert ack_3["t"] == "ack" and ack_3["d"]["ok"] is True

            hand_starts = {3: hand_start_3}
            deals = {3: deal_3}
            turns = {3: turn_3}
            for seat in range(3):
                hand_starts[seat] = wss[seat].receive_json()
                deals[seat] = wss[seat].receive_json()
                turns[seat] = wss[seat].receive_json()

            expected_hands = {
                0: (*_SEAT0_JUNK, _MAN_5[0]),
                1: (_MAN_4[0], _MAN_6[0], *_SEAT1_JUNK),
                2: (_MAN_5[1], _MAN_5[2], *_SEAT2_JUNK),
                3: _SEAT3_JUNK,
            }
            for seat in range(4):
                assert hand_starts[seat]["t"] == "hand_start"
                assert hand_starts[seat]["d"]["hand_no"] == 1
                assert hand_starts[seat]["d"]["dealer"] == 0
                assert deals[seat]["t"] == "deal"
                assert sorted(deals[seat]["d"]["your_hand"]) == sorted(expected_hands[seat])
                assert turns[seat]["t"] == "turn"
                assert turns[seat]["d"]["seat"] == 0
            assert "legal" in turns[0]["d"] and turns[0]["d"]["legal"]
            assert "legal" not in turns[1]["d"]

            # --- seat 0 discards 5m: broadcast discard (with tile/pool_index filled in), then
            # claim_offer unicast to seats 1 (chow) and 2 (pung) only -- seat 3 gets neither.
            discard_id = _next_id()
            wss[0].send_json(_msg("discard", {"tile_id": _MAN_5[0]}, id_=discard_id))
            ack_d0 = wss[0].receive_json()
            assert ack_d0["d"] == {"id": discard_id, "ok": True}

            discards = {seat: ws.receive_json() for seat, ws in enumerate(wss)}
            for seat in range(4):
                assert discards[seat]["t"] == "discard"
                assert discards[seat]["d"]["seat"] == 0
                assert discards[seat]["d"]["tile_id"] == _MAN_5[0]
                assert discards[seat]["d"]["pool_index"] == 0

            offer1 = wss[1].receive_json()
            assert offer1["t"] == "claim_offer"
            assert {o["kind"] for o in offer1["d"]["options"]} == {"chow", "pass"}

            offer2 = wss[2].receive_json()
            assert offer2["t"] == "claim_offer"
            assert {o["kind"] for o in offer2["d"]["options"]} == {"pung", "pass"}
            window_id = offer2["d"]["window_id"]

            # an option's `tiles` names only the claimer's own tiles, never the discard, so a
            # client can echo it straight back as the claim disambiguator (02-protocol.md §2).
            pung_option = next(o for o in offer2["d"]["options"] if o["kind"] == "pung")
            assert sorted(pung_option["tiles"]) == sorted([_MAN_5[1], _MAN_5[2]])

            # --- seat 2 pungs (higher priority than seat 1's un-answered chow -- early exit,
            # 00-architecture.md §4). No response is ever sent for seat 1's offer.
            claim_id = _next_id()
            wss[2].send_json(
                _msg(
                    "claim",
                    {"window_id": window_id, "choice": "pung", "tiles": pung_option["tiles"]},
                    id_=claim_id,
                )
            )
            ack_c2 = wss[2].receive_json()
            assert ack_c2["d"] == {"id": claim_id, "ok": True}

            resolved = {seat: ws.receive_json() for seat, ws in enumerate(wss)}
            for seat in range(4):
                assert resolved[seat]["t"] == "claim_resolved"
                assert resolved[seat]["d"]["seat"] == 2
                assert resolved[seat]["d"]["claim_kind"] == "discard"
                assert resolved[seat]["d"]["action_kind"] == "claim_pung"

            melds = {seat: ws.receive_json() for seat, ws in enumerate(wss)}
            for seat in range(4):
                assert melds[seat]["t"] == "meld"
                assert melds[seat]["d"]["seat"] == 2
                assert melds[seat]["d"]["meld_kind"] == "pung"
                assert sorted(melds[seat]["d"]["tiles"]) == sorted(
                    [_MAN_5[0], _MAN_5[1], _MAN_5[2]]
                )

            post_pung_turns = {seat: ws.receive_json() for seat, ws in enumerate(wss)}
            for seat in range(4):
                assert post_pung_turns[seat]["t"] == "turn"
                assert post_pung_turns[seat]["d"]["seat"] == 2
            legal2 = post_pung_turns[2]["d"]["legal"]
            discard_action = next(a for a in legal2 if a["kind"] == "discard")

            # seat 2 discards a junk tile: nobody claims it, so reduce() cascades straight to
            # wall-exhausted hand over, and Table chains start_next_hand() into hand 2 same tick.
            discard2_id = _next_id()
            wss[2].send_json(
                _msg("discard", {"tile_id": discard_action["tile_id"]}, id_=discard2_id)
            )
            ack_d2 = wss[2].receive_json()
            assert ack_d2["d"] == {"id": discard2_id, "ok": True}

            expected_types = ["discard", "hand_end", "score"]
            frames: dict[int, list[dict[str, object]]] = {s: [] for s in range(4)}
            for _ in expected_types:
                for seat, ws in enumerate(wss):
                    frames[seat].append(ws.receive_json())

            for seat in range(4):
                assert [f["t"] for f in frames[seat]] == expected_types

            hand_end = _payload(frames[0][1])
            assert hand_end["outcome"] == "exhaustive_draw"
            assert hand_end["hand_no"] == 1
            assert hand_end["winner"] is None
            # hand-end hold (docs/00-architecture.md §3): every seat gets the same deadline,
            # held until all four ack (below) or it elapses, whichever first.
            assert isinstance(hand_end["deadline_ts"], int)

            score = _payload(frames[0][2])
            assert score["totals"] == {"0": 0, "1": 0, "2": 0, "3": 0}

            # hand-end hold needs all 4 hand_end_ack's before the next hand starts (same "wait
            # for all 4" shape as ready above); the 4th ack cascades hand_start/deal/turn synchronously, landing ahead of its own ack, like ack_3 above.
            for seat in range(3):
                ack_id = _next_id()
                wss[seat].send_json(_msg("hand_end_ack", {}, id_=ack_id))
                ack = wss[seat].receive_json()
                assert ack["d"] == {"id": ack_id, "ok": True}

            ack3_id = _next_id()
            wss[3].send_json(_msg("hand_end_ack", {}, id_=ack3_id))
            next_hand_start_3 = wss[3].receive_json()
            next_deal_3 = wss[3].receive_json()
            next_turn_3 = wss[3].receive_json()
            next_ack_3 = wss[3].receive_json()
            assert next_ack_3["d"] == {"id": ack3_id, "ok": True}

            next_types = ["hand_start", "deal", "turn"]
            next_frames: dict[int, list[dict[str, object]]] = {
                3: [next_hand_start_3, next_deal_3, next_turn_3]
            }
            for seat in range(3):
                next_frames[seat] = [wss[seat].receive_json() for _ in next_types]

            for seat in range(4):
                assert [f["t"] for f in next_frames[seat]] == next_types

            next_hand_start = _payload(next_frames[0][0])
            assert next_hand_start["hand_no"] == 2
            assert next_hand_start["dealer"] == 0  # dealer repeats on exhaustive draw (default)

            next_turn = _payload(next_frames[0][2])
            assert next_turn["seat"] == 0


def test_duplicate_id_same_payload_resends_ack_different_payload_is_rejected() -> None:
    table_id = f"idempotency-{uuid.uuid4()}"

    with TestClient(app) as client, client.websocket_connect(f"/ws?table={table_id}") as ws:
        ws.send_json(_msg("hello", {"client_version": "test"}))
        ws.send_json(_msg("join", {"seat": 0}, id_=_next_id()))
        assert ws.receive_json()["t"] == "seat_state"
        assert ws.receive_json()["t"] == "state_sync"
        join_ack = ws.receive_json()
        assert join_ack["d"]["ok"] is True

        table = get_table(table_id)
        assert table is not None
        tile_a, tile_b = table.state.seats[table.state.turn].concealed[:2]

        # not necessarily this seat's turn -- irrelevant to the id contract, which fires
        # before Table judges legality; an illegal command is just dropped silently, unrelated to this test.
        ws.send_json(_msg("discard", {"tile_id": int(tile_a)}, id_="d-1"))
        first_ack = ws.receive_json()
        assert first_ack["d"] == {"id": "d-1", "ok": True}

        # exact retry: same id, same payload -> re-sent ack, not reapplied.
        ws.send_json(_msg("discard", {"tile_id": int(tile_a)}, id_="d-1"))
        retry_ack = ws.receive_json()
        assert retry_ack["d"] == {"id": "d-1", "ok": True}

        # same id, different payload -> rejected, neither payload applied.
        ws.send_json(_msg("discard", {"tile_id": int(tile_b)}, id_="d-1"))
        conflict_ack = ws.receive_json()
        assert conflict_ack["d"]["ok"] is False
        assert conflict_ack["d"]["error"] == "id_conflict"

        # a genuinely illegal claim (unknown window) still gets ok=False without ever
        # reaching Table.submit -- and is itself idempotent under the same id contract.
        ws.send_json(_msg("claim", {"window_id": 999999, "choice": "pass"}, id_="bad-1"))
        bad_ack = ws.receive_json()
        assert bad_ack["d"] == {"id": "bad-1", "ok": False, "error": "illegal"}

        ws.send_json(_msg("claim", {"window_id": 999999, "choice": "pass"}, id_="bad-1"))
        bad_ack_retry = ws.receive_json()
        assert bad_ack_retry["d"] == {"id": "bad-1", "ok": False, "error": "illegal"}


def test_join_seat_status_distinguishes_never_joined_from_connected() -> None:
    """A lobby client (fewer than four seats bound) needs `state_sync.d.seat_status` to tell
    "nobody has ever joined this seat" apart from "someone's here and connected" -- the signal
    the `/table/[id]` waiting-table screen renders off. Also confirms a later `join` broadcasts
    `seat_state` live to already-connected seats, not just the new joiner's own snapshot."""
    table_id = f"seat-status-{uuid.uuid4()}"

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws0,
        client.websocket_connect(f"/ws?table={table_id}") as ws1,
    ):
        ws0.send_json(_msg("hello", {"client_version": "test"}))
        ws1.send_json(_msg("hello", {"client_version": "test"}))

        # --- seat 0 joins alone: its own state_sync sees itself connected, every other seat
        # (never joined by anyone) as empty -- not "connected", the pre-fix behavior.
        ws0.send_json(_msg("join", {"seat": 0, "name": "Alice"}, id_=_next_id()))
        assert ws0.receive_json()["t"] == "seat_state"  # its own join, broadcast to itself
        sync0 = ws0.receive_json()
        assert sync0["t"] == "state_sync"
        assert sync0["d"]["seat_status"] == ["connected", "empty", "empty", "empty"]
        # M5: names mirror seat_status -- a resolved name for a bound seat, null for an empty one.
        assert sync0["d"]["names"] == ["Alice", None, None, None]
        ack0 = ws0.receive_json()
        assert ack0["d"]["ok"] is True

        # seat 1 joins: seat 0 sees a live seat_state broadcast (not just its next resync), and
        # seat 1's fresh state_sync already reflects both bound seats as connected.
        ws1.send_json(_msg("join", {"seat": 1, "name": "Bob"}, id_=_next_id()))
        live_update = ws0.receive_json()
        assert live_update["t"] == "seat_state"
        assert live_update["d"] == {"seat": 1, "status": "connected", "name": "Bob"}

        assert ws1.receive_json()["t"] == "seat_state"  # seat 1's own join, broadcast to itself
        sync1 = ws1.receive_json()
        assert sync1["t"] == "state_sync"
        assert sync1["d"]["seat_status"] == ["connected", "connected", "empty", "empty"]
        assert sync1["d"]["names"] == ["Alice", "Bob", None, None]
        ack1 = ws1.receive_json()
        assert ack1["d"]["ok"] is True


def test_host_is_first_joiner_and_start_with_bots_fills_and_starts() -> None:
    """First `join` becomes host (docs' "Host definition": first-to-join, not seat 0) -- proven
    here by having seat 2 join before seat 0. The host's `start_with_bots` binds every still-
    empty seat to a bot (M4.5's `_bind_bot_seat`, invoked at runtime instead of only at table
    construction), broadcasts `seat_state{status:"bot"}` for each, and starts the hand the
    moment that makes every seat bound and ready -- exactly like a fourth human's `ready` would.
    A non-host `start_with_bots` is rejected with `not_host`; a second one, once the hand's
    already dealt, with `already_started`."""
    table_id = f"start-with-bots-{uuid.uuid4()}"

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}") as ws2,
        client.websocket_connect(f"/ws?table={table_id}") as ws0,
    ):
        ws2.send_json(_msg("hello", {"client_version": "test"}))
        ws0.send_json(_msg("hello", {"client_version": "test"}))

        # seat 2 joins first -> becomes host, even though it isn't seat 0.
        ws2.send_json(_msg("join", {"seat": 2, "name": "Carol"}, id_=_next_id()))
        assert ws2.receive_json()["t"] == "seat_state"
        sync2 = ws2.receive_json()
        assert sync2["t"] == "state_sync"
        assert sync2["d"]["host_seat"] == 2
        assert ws2.receive_json()["d"]["ok"] is True
        ws2.send_json(_msg("ready", {}, id_=_next_id()))
        assert ws2.receive_json()["d"]["ok"] is True  # seats 0/1/3 still open -- not started yet

        # seat 0 joins second -> not host.
        ws0.send_json(_msg("join", {"seat": 0, "name": "Alice"}, id_=_next_id()))
        assert ws2.receive_json()["t"] == "seat_state"  # live update to the already-joined host
        assert ws0.receive_json()["t"] == "seat_state"
        sync0 = ws0.receive_json()
        assert sync0["t"] == "state_sync"
        assert sync0["d"]["host_seat"] == 2
        assert ws0.receive_json()["d"]["ok"] is True

        # a non-host start_with_bots is rejected outright -- nothing bound, nothing started.
        ws0.send_json(_msg("start_with_bots", {}, id_=_next_id()))
        not_host_ack = ws0.receive_json()
        assert not_host_ack["t"] == "ack"
        assert not_host_ack["d"]["ok"] is False
        assert not_host_ack["d"]["error"] == "not_host"

        ws0.send_json(_msg("ready", {}, id_=_next_id()))
        assert ws0.receive_json()["d"]["ok"] is True

        # the host fills seats 1 and 3 with bots and the hand starts immediately.
        ws2.send_json(_msg("start_with_bots", {}, id_=_next_id()))
        bot_seat_states = [ws2.receive_json(), ws2.receive_json()]
        assert {f["d"]["seat"] for f in bot_seat_states} == {1, 3}
        assert all(f["t"] == "seat_state" and f["d"]["status"] == "bot" for f in bot_seat_states)

        assert ws2.receive_json()["t"] == "hand_start"
        assert ws2.receive_json()["t"] == "deal"
        assert ws2.receive_json()["t"] == "turn"
        start_ack = ws2.receive_json()
        assert start_ack["t"] == "ack"
        assert start_ack["d"]["ok"] is True

        # already started -- even the host's second start_with_bots is rejected.
        ws2.send_json(_msg("start_with_bots", {}, id_=_next_id()))
        already_ack = ws2.receive_json()
        assert already_ack["t"] == "ack"
        assert already_ack["d"]["ok"] is False
        assert already_ack["d"]["error"] == "already_started"
