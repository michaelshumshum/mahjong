"""Real gameplay over the wire (docs/05-roadmap.md M3 sub-task 4) -- the M3 gate in miniature:
four scripted WS clients `join` the same room, `ready` up, and play a hand through real
`discard`/`claim`/`declare` intents, asserting correctly-sequenced, correctly-redacted frames.

The mid-hand fixture (seat 0 discards 5m, seat 1 can chow it, seat 2 can pung it, seat 3 holds
nothing relevant) is `tests/test_room_claims.py`'s exact fixture, injected the same white-box
way that module already established (`room.state = ...`) -- here additionally with an emptied
wall, so the hand ends in a fast, deterministic exhaustive draw right after the pung resolves
and its claimant discards, instead of needing to hand-craft a real winning hand or play out
however much of the wall real random legal actions would need. That still exercises a full
hand boundary (`hand_end`, `score`, and the next hand's `hand_start`/`deal`/`turn`) over the
real wire, not just the claim exchange.

Every read below is a *blocking* `receive_json()` on a specific connection's queue, never a
raw count-mismatch risk: a session's own outbound stream is strictly FIFO in true production
order (`app/room.py`'s `Room.publish_to_seat`), so reading a known, derivable number of frames
off a specific connection can only return exactly those frames in that order -- there is
nothing to race. The one thing to get right is *how many* frames a given step produces per
connection, which is computed here the same way `Room` produces it (a broadcast reaches every
currently-bound seat; a unicast reaches one), not hand-counted.
"""

from __future__ import annotations

import dataclasses
import itertools
import time
import uuid

from fastapi.testclient import TestClient

from app.main import app
from app.ws import get_room
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


# Unlike tests/test_room_claims.py's fixture (which never drives play past the pung, so its
# junk tiles can safely repeat the same physical ids across seats), this test plays a second
# discard for real -- so every seat's junk needs to be both physically distinct (no tile_id
# reused across two seats -- mahjong_core has no cross-seat uniqueness check of its own, so a
# reused id silently builds an impossible "3 physical copies of one tile" meld the moment it's
# claimed) *and* type-exclusive per seat (no other seat may hold a type matching whatever seat
# 2 goes on to discard, or that discard would open a real, unscripted claim window). Each
# seat's junk pool below draws from its own dedicated tile types -- honors for seat 2 in
# particular, which can never form a chow at all, making its discard doubly claim-proof.
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
    room_id = f"gameplay-{uuid.uuid4()}"

    with TestClient(app) as client, client.websocket_connect(f"/ws?room={room_id}") as ws0:
        room = get_room(room_id)
        assert room is not None
        room.state = _rig_state(seed=20260916)

        with (
            client.websocket_connect(f"/ws?room={room_id}") as ws1,
            client.websocket_connect(f"/ws?room={room_id}") as ws2,
            client.websocket_connect(f"/ws?room={room_id}") as ws3,
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
                        assert frame["d"] == {"seat": seat, "status": "connected"}
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

            # --- seat 2 pungs (higher priority than seat 1's un-answered chow -- early exit,
            # 00-architecture.md §4). No response is ever sent for seat 1's offer.
            claim_id = _next_id()
            wss[2].send_json(
                _msg("claim", {"window_id": window_id, "choice": "pung"}, id_=claim_id)
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

            # --- seat 2 discards a junk tile: nobody can claim it, so the engine cascades
            # straight through "advance to seat 3's draw" -> wall exhausted -> hand over --
            # all inside this one reduce() call, then Room chains start_next_hand() into a
            # fresh hand 2 in the same tick (app/room.py's `_apply`).
            discard2_id = _next_id()
            wss[2].send_json(
                _msg("discard", {"tile_id": discard_action["tile_id"]}, id_=discard2_id)
            )
            ack_d2 = wss[2].receive_json()
            assert ack_d2["d"] == {"id": discard2_id, "ok": True}

            expected_types = ["discard", "hand_end", "score", "hand_start", "deal", "turn"]
            frames: dict[int, list[dict[str, object]]] = {s: [] for s in range(4)}
            for _ in expected_types:
                for seat, ws in enumerate(wss):
                    frames[seat].append(ws.receive_json())

            for seat in range(4):
                assert [f["t"] for f in frames[seat]] == expected_types

            hand_end = frames[0][1]["d"]
            assert hand_end["outcome"] == "exhaustive_draw"
            assert hand_end["hand_no"] == 1
            assert hand_end["winner"] is None

            score = frames[0][2]["d"]
            assert score["totals"] == {"0": 0, "1": 0, "2": 0, "3": 0}

            next_hand_start = frames[0][3]["d"]
            assert next_hand_start["hand_no"] == 2
            assert next_hand_start["dealer"] == 0  # dealer repeats on exhaustive draw (default)

            next_turn = frames[0][5]["d"]
            assert next_turn["seat"] == 0


def test_duplicate_id_same_payload_resends_ack_different_payload_is_rejected() -> None:
    room_id = f"idempotency-{uuid.uuid4()}"

    with TestClient(app) as client, client.websocket_connect(f"/ws?room={room_id}") as ws:
        ws.send_json(_msg("hello", {"client_version": "test"}))
        ws.send_json(_msg("join", {"seat": 0}, id_=_next_id()))
        assert ws.receive_json()["t"] == "seat_state"
        assert ws.receive_json()["t"] == "state_sync"
        join_ack = ws.receive_json()
        assert join_ack["d"]["ok"] is True

        room = get_room(room_id)
        assert room is not None
        tile_a, tile_b = room.state.seats[room.state.turn].concealed[:2]

        # not this seat's turn (seat 0 may not even be the dealer here) -- irrelevant to the
        # id contract itself, which fires before Room ever gets to judge legality; Room simply
        # drops the command silently if it isn't actually legal (unchanged sub-task 2/3
        # behavior), and this test only cares about the ack/idempotency layer above that.
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
        # reaching Room.submit -- and is itself idempotent under the same id contract.
        ws.send_json(_msg("claim", {"window_id": 999999, "choice": "pass"}, id_="bad-1"))
        bad_ack = ws.receive_json()
        assert bad_ack["d"] == {"id": "bad-1", "ok": False, "error": "illegal"}

        ws.send_json(_msg("claim", {"window_id": 999999, "choice": "pass"}, id_="bad-1"))
        bad_ack_retry = ws.receive_json()
        assert bad_ack_retry["d"] == {"id": "bad-1", "ok": False, "error": "illegal"}
