"""Real spectator support over the wire (
docs/architecture.md §3/§5's spectator sketch; docs/protocol.md §2/§5). A connection that
opts in via `?spectate=true` (see `app/table.py`'s `Table.register_spectator` docstring for why
this is an explicit connect-time flag, not the literal passive default docs/protocol.md §2
describes) gets the same `seat_view(state, None)`-shaped stream `tests/test_redaction.py`'s
schema walker has always exercised statically -- this module is the first thing that actually
drives a live connection through it.

Fixture: seat 0 on turn holding 5m plus junk; seat 2 can pung it (holds two more 5m); seats 1
and 3 hold nothing relevant (no chow eligibility, unlike `tests/test_ws_gameplay.py`'s own
`_rig_state` -- simplified here since this module only needs *a* claim, not every claim kind).
Wall emptied so the hand ends in exhaustive draw right after the pung's claimant discards.
"""

from __future__ import annotations

import dataclasses
import itertools
import uuid

from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import GameState, Phase
from mahjong_core.tiles import TileType, tile_ids_for_type
from tests.game_state import with_seat
from tests.tables import table_client
from tests.ws_frames import first_tile_ids, msg, next_id

_MAN_5 = tile_ids_for_type(TileType.MAN_5)


_SEAT0_JUNK = first_tile_ids(
    TileType.PIN_2, TileType.PIN_4, TileType.PIN_6, TileType.PIN_8, count=13
)
_SEAT1_JUNK = first_tile_ids(
    TileType.SOU_2, TileType.SOU_4, TileType.SOU_6, TileType.SOU_8, count=13
)
_SEAT2_JUNK = first_tile_ids(TileType.WIND_EAST, TileType.WIND_SOUTH, TileType.WIND_WEST, count=11)
_SEAT3_JUNK = first_tile_ids(
    TileType.DRAGON_RED, TileType.DRAGON_GREEN, TileType.DRAGON_WHITE, TileType.WIND_NORTH, count=13
)


def _rig_state(seed: int) -> GameState:
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    state = with_seat(state, 0, concealed=(*_SEAT0_JUNK, _MAN_5[0]), discards=())
    state = with_seat(state, 1, concealed=_SEAT1_JUNK)
    state = with_seat(state, 2, concealed=(_MAN_5[1], _MAN_5[2], *_SEAT2_JUNK))
    state = with_seat(state, 3, concealed=_SEAT3_JUNK)
    return dataclasses.replace(state, wall=dataclasses.replace(state.wall, tiles=()))


def test_spectator_gets_state_sync_then_live_events_with_dense_seq() -> None:
    table_id = f"spectator-{uuid.uuid4()}"

    with table_client(table_id) as client, client.websocket_connect(f"/ws?table={table_id}") as ws0:
        table = get_table(table_id)
        assert table is not None
        table.state = _rig_state(seed=20260920)

        with (
            client.websocket_connect(f"/ws?table={table_id}") as ws1,
            client.websocket_connect(f"/ws?table={table_id}") as ws2,
            client.websocket_connect(f"/ws?table={table_id}") as ws3,
            client.websocket_connect(f"/ws?table={table_id}&spectate=true") as spectator,
        ):
            wss = [ws0, ws1, ws2, ws3]
            spec_seq = itertools.count()

            # immediately on connect: a real spectator-shaped state_sync (seat=None), no
            # private hand data for any seat (architecture.md §5).
            sync = spectator.receive_json()
            assert sync["t"] == "state_sync"
            assert sync["seq"] == next(spec_seq)
            assert sync["d"]["seat"] is None
            assert sync["d"]["own_hand"] == []
            assert sync["d"]["legal_actions"] == []
            assert sync["d"]["claim_options"] == []

            for ws in wss:
                ws.send_json(msg("hello", {"client_version": "test"}))

            # --- join all four real seats; the spectator sees each `seat_state` broadcast too,
            # exactly once per join, same as every already-bound seat does.
            bound = [False, False, False, False]
            for seat, ws in enumerate(wss):
                ws.send_json(msg("join", {"seat": seat}, id_=next_id()))
                bound[seat] = True
                for s, other in enumerate(wss):
                    if bound[s]:
                        assert other.receive_json()["t"] == "seat_state"
                assert ws.receive_json()["t"] == "state_sync"
                ack = ws.receive_json()
                assert ack["t"] == "ack" and ack["d"]["ok"] is True

                spec_frame = spectator.receive_json()
                assert spec_frame["t"] == "seat_state"
                assert spec_frame["seq"] == next(spec_seq)
                assert spec_frame["d"]["seat"] == seat

            # --- ready all four; the spectator gets the broadcast `hand_start` (never the
            # per-seat private `deal`) and the public half of `turn` (no `legal`).
            for seat in range(3):
                wss[seat].send_json(msg("ready", {}, id_=next_id()))
                ack = wss[seat].receive_json()
                assert ack["t"] == "ack" and ack["d"]["ok"] is True

            wss[3].send_json(msg("ready", {}, id_=next_id()))
            for ws in wss:
                assert ws.receive_json()["t"] == "hand_start"
                assert ws.receive_json()["t"] == "deal"
                assert ws.receive_json()["t"] == "turn"
            ack3 = wss[3].receive_json()
            assert ack3["t"] == "ack" and ack3["d"]["ok"] is True

            spec_hand_start = spectator.receive_json()
            assert spec_hand_start["t"] == "hand_start"
            assert spec_hand_start["seq"] == next(spec_seq)

            spec_turn0 = spectator.receive_json()
            assert spec_turn0["t"] == "turn"
            assert spec_turn0["seq"] == next(spec_seq)
            assert spec_turn0["d"]["seat"] == 0
            assert "legal" not in spec_turn0["d"]

            # seat 0 discards 5m: claim_offer unicasts to seat 2 only -- the spectator must
            # never see it (would leak seat 2's concealed tiles), only the public discard.
            discard_id = next_id()
            ws0.send_json(msg("discard", {"tile_id": _MAN_5[0]}, id_=discard_id))
            ack_d0 = ws0.receive_json()
            assert ack_d0["d"] == {"id": discard_id, "ok": True}

            for ws in wss:
                assert ws.receive_json()["t"] == "discard"

            spec_discard = spectator.receive_json()
            assert spec_discard["t"] == "discard"
            assert spec_discard["seq"] == next(spec_seq)
            assert spec_discard["d"]["seat"] == 0
            assert spec_discard["d"]["tile_id"] == _MAN_5[0]
            assert spec_discard["d"]["pool_index"] == 0

            offer2 = ws2.receive_json()
            assert offer2["t"] == "claim_offer"
            window_id = offer2["d"]["window_id"]
            pung_option = next(o for o in offer2["d"]["options"] if o["kind"] == "pung")

            # seat 2 pungs: the next frame this spectator sees is `claim_resolved`, never the
            # claim_offer that preceded it -- proving the offer really was unicast-only.
            claim_id = next_id()
            ws2.send_json(
                msg(
                    "claim",
                    {"window_id": window_id, "choice": "pung", "tiles": pung_option["tiles"]},
                    id_=claim_id,
                )
            )
            ack_c2 = ws2.receive_json()
            assert ack_c2["d"] == {"id": claim_id, "ok": True}

            for ws in wss:
                assert ws.receive_json()["t"] == "claim_resolved"
            for ws in wss:
                assert ws.receive_json()["t"] == "meld"
            for ws in wss:
                assert ws.receive_json()["t"] == "turn"

            spec_resolved = spectator.receive_json()
            assert spec_resolved["t"] == "claim_resolved"
            assert spec_resolved["seq"] == next(spec_seq)
            assert spec_resolved["d"]["seat"] == 2

            spec_meld = spectator.receive_json()
            assert spec_meld["t"] == "meld"
            assert spec_meld["seq"] == next(spec_seq)
            assert sorted(spec_meld["d"]["tiles"]) == sorted([_MAN_5[0], _MAN_5[1], _MAN_5[2]])

            spec_turn2 = spectator.receive_json()
            assert spec_turn2["t"] == "turn"
            assert spec_turn2["seq"] == next(spec_seq)
            assert spec_turn2["d"]["seat"] == 2
            assert "legal" not in spec_turn2["d"]

            # seat 2 discards a junk tile (post-pung hand is deterministically `_SEAT2_JUNK`);
            # nobody claims it and the wall is empty, so it cascades discard -> hand_end -> score.
            discard2_id = next_id()
            ws2.send_json(msg("discard", {"tile_id": _SEAT2_JUNK[0]}, id_=discard2_id))
            ack_d2 = ws2.receive_json()
            assert ack_d2["d"] == {"id": discard2_id, "ok": True}

            for ws in wss:
                assert ws.receive_json()["t"] == "discard"
            for ws in wss:
                assert ws.receive_json()["t"] == "hand_end"
            for ws in wss:
                assert ws.receive_json()["t"] == "score"

            spec_discard2 = spectator.receive_json()
            assert spec_discard2["t"] == "discard"
            assert spec_discard2["seq"] == next(spec_seq)
            assert spec_discard2["d"]["seat"] == 2

            spec_hand_end = spectator.receive_json()
            assert spec_hand_end["t"] == "hand_end"
            assert spec_hand_end["seq"] == next(spec_seq)
            assert spec_hand_end["d"]["outcome"] == "exhaustive_draw"

            spec_score = spectator.receive_json()
            assert spec_score["t"] == "score"
            assert spec_score["seq"] == next(spec_seq)


def test_multiple_spectators_have_independent_dense_seq_streams() -> None:
    table_id = f"spectator-multi-{uuid.uuid4()}"
    with (
        table_client(table_id) as client,
        client.websocket_connect(f"/ws?table={table_id}&spectate=true") as spec_a,
        client.websocket_connect(f"/ws?table={table_id}&spectate=true") as spec_b,
    ):
        table = get_table(table_id)
        assert table is not None
        assert len(table.spectators) == 2

        sync_a = spec_a.receive_json()
        sync_b = spec_b.receive_json()
        assert sync_a["t"] == sync_b["t"] == "state_sync"
        assert sync_a["seq"] == 0
        assert sync_b["seq"] == 0  # independent counters -- both start at their own 0

        table.broadcast_server_shutdown(123)
        assert spec_a.receive_json()["seq"] == 1
        assert spec_b.receive_json()["seq"] == 1

        table.broadcast_server_shutdown(456)
        assert spec_a.receive_json()["seq"] == 2
        assert spec_b.receive_json()["seq"] == 2

        # white-box: both sessions' own next-seq counters advanced identically but
        # independently -- two distinct dict entries, not one shared counter.
        assert len(table.spectator_seq) == 2
        assert set(table.spectator_seq.values()) == {3}


def test_join_from_spectating_connection_promotes_and_stops_duplicate_stream() -> None:
    table_id = f"spectator-promote-{uuid.uuid4()}"
    with (
        table_client(table_id) as client,
        client.websocket_connect(f"/ws?table={table_id}&spectate=true") as ws,
    ):
        table = get_table(table_id)
        assert table is not None
        assert len(table.spectators) == 1

        sync = ws.receive_json()
        assert sync["t"] == "state_sync" and sync["d"]["seat"] is None

        ws.send_json(msg("join", {"seat": 0}, id_=next_id()))
        seat_state = ws.receive_json()
        assert seat_state["t"] == "seat_state" and seat_state["d"]["seat"] == 0
        real_sync = ws.receive_json()
        assert real_sync["t"] == "state_sync" and real_sync["d"]["seat"] == 0
        ack = ws.receive_json()
        assert ack["t"] == "ack" and ack["d"]["ok"] is True

        # promoted: no spectator bookkeeping survives for this session -- `table.ring` is back
        # to exactly the four integer seat keys, nothing else.
        assert table.spectators == {}
        assert table.spectator_seq == {}
        assert set(table.ring.keys()) == {0, 1, 2, 3}

        # a further live event (seat 1 joining) reaches this connection exactly once, through
        # its now-real seat stream -- not doubled by a leftover spectator registration.
        with client.websocket_connect(f"/ws?table={table_id}") as ws1:
            ws1.send_json(msg("join", {"seat": 1}, id_=next_id()))
            live_update = ws.receive_json()
            assert live_update["t"] == "seat_state" and live_update["d"]["seat"] == 1


def test_spectator_bookkeeping_removed_on_disconnect() -> None:
    table_id = f"spectator-cleanup-{uuid.uuid4()}"
    with table_client(table_id) as client:
        with client.websocket_connect(f"/ws?table={table_id}&spectate=true") as spectator:
            table = get_table(table_id)
            assert table is not None
            assert len(table.spectators) == 1
            [session_id] = list(table.spectators)
            assert session_id in table.ring
            assert session_id in table.spectator_seq
            spectator.receive_json()  # drain the initial state_sync

        # connection closed -- app/ws.py's `finally` block calls `unregister_spectator`, same
        # call site `mark_disconnected` uses for a seat's own disconnect cleanup.
        assert table.spectators == {}
        assert table.spectator_seq == {}
        assert session_id not in table.ring
