"""M4.5's bot-filled-table mechanism (docs/05-roadmap.md M4.5, docs/04-bots.md §1): one real WS
client joins a `practice=true` table, seats 1-3 are bot-bound from table *creation* -- no `join`
ever sent for them -- and a full game plays out to `Phase.GAME_OVER` with the human acting on
its own turns and the real `FaanBot` (T2, the table's default `bot_tier`) tier acting on the
bots'. Deliberately **not** a scripted hand (`tests/test_full_game_e2e.py`'s own style rigs
every hand's tiles): proving the mechanism means letting `_poke_bots()`/the real
`ProcessPoolExecutor` round-trip actually decide the bots' moves, turn after turn, for a whole
game -- see `_play_practice_game`'s docstring for the (always-legal, deliberately simple) human
policy that keeps this deterministic-enough to assert on without needing to predict what three
real heuristic bots do with an unrigged wall. Not marked `slow` (like
`tests/test_full_game_e2e.py`'s own comparable real 4-hand WS-driven game): a fixed seed keeps
this one fast in practice (a couple of seconds, including `ProcessPoolExecutor` worker
start-up) -- unlike `tests/test_selfplay.py`'s genuinely heavy 10,000-game/200-hypothesis-example
sweeps, this is a single deterministic run.

`_GAME_RULESET` (dealer-repeat off, same as `test_full_game_e2e.py`'s own) is applied by
directly overwriting `table.state` with a freshly-dealt `GameState` right after the table is
created (same technique that file already established) -- `ws_endpoint` has no query param to
choose a ruleset, only `DEFAULT_RULESET` (dealer-repeat *on*), which would make hand count
unbounded and this test unpredictably slow rather than a bounded, fast, deterministic run.
"""

from __future__ import annotations

import dataclasses
import itertools
import time
import uuid
from typing import Any, cast

from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession

from app.main import app
from app.ws import get_table
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.engine import new_game
from mahjong_core.state import Phase

_id_gen = itertools.count(1)

# same rationale as tests/test_full_game_e2e.py's own _GAME_RULESET: with both dealer-repeat
# flags off, EAST_ONLY is bounded at exactly 4 hands (dealer 0 -> 1 -> 2 -> 3, then GAME_OVER)
# regardless of how any individual hand ends -- required so a *real*, unscripted game (this
# test's whole point) terminates in bounded time.
_GAME_RULESET = dataclasses.replace(
    DEFAULT_RULESET, dealer_repeat_on_win=False, dealer_repeat_on_draw=False
)


def _ts() -> int:
    return time.time_ns() // 1_000_000


def _msg(t: str, d: dict[str, object], *, id_: str | None = None) -> dict[str, object]:
    frame: dict[str, object] = {"v": 1, "t": t, "ts": _ts(), "d": d}
    if id_ is not None:
        frame["id"] = id_
    return frame


def _next_id() -> str:
    return f"c-{next(_id_gen)}"


def _play_practice_game(ws: WebSocketTestSession) -> list[dict[str, Any]]:
    """Drive the human seat (0) through a real, unscripted game until `game_end`: take a win
    the instant it's legal, otherwise always discard the first legal `discard` option, and
    always `pass` on a claim offer. This is deliberately the simplest policy that is *always*
    legal (mahjong_core's own invariant: `legal_actions` is never empty in an active phase, and
    an `AWAIT_ACTION` turn always offers at least one `discard` unless a win is already being
    taken) -- it never leaves the human stuck, so the game's actual pace and outcome are driven
    for real by the wall and by seats 1-3's real `FaanBot` decisions, not by anything scripted
    here. Every frame is collected and returned so the caller can assert on the full trace.
    """
    frames: list[dict[str, Any]] = []
    while True:
        frame = cast("dict[str, Any]", ws.receive_json())
        frames.append(frame)
        t = frame["t"]
        d = frame["d"]
        if t == "game_end":
            return frames
        if t == "turn" and "legal" in d:
            legal = d["legal"]
            win = next((a for a in legal if a["kind"] == "win"), None)
            if win is not None:
                ws.send_json(_msg("declare", {"kind": "win"}, id_=_next_id()))
                continue
            discard = next(a for a in legal if a["kind"] == "discard")
            ws.send_json(_msg("discard", {"tile_id": discard["tile_id"]}, id_=_next_id()))
        elif t == "claim_offer":
            ws.send_json(
                _msg("claim", {"window_id": d["window_id"], "choice": "pass"}, id_=_next_id())
            )


def test_practice_mode_full_game_against_real_faanbots() -> None:
    table_id = f"practice-{uuid.uuid4()}"
    seed = 20260918001

    with (
        TestClient(app) as client,
        client.websocket_connect(f"/ws?table={table_id}&practice=true") as ws0,
    ):
        table = get_table(table_id)
        assert table is not None

        # --- seats 1-3 are bot-bound from table *creation*, before this test ever sends `join`
        # for anyone -- the whole point of this sub-task's mechanism.
        assert table.seat_bindings[0] is None
        for seat in (1, 2, 3):
            binding = table.seat_bindings[seat]
            assert binding is not None
            assert binding.status == "bot"
            assert binding.ready is True
            # M5: a bot seat still gets a real, sensible display name -- never null/empty --
            # sourced from the table's real tier, not a generic "Bot" placeholder.
            assert binding.name == "FaanBot"
        assert table._bot_tier == "T2"  # M4.5's default -- FaanBot, not a weaker tier

        # override to a repeat-off ruleset (module docstring) -- before any message is sent, so
        # every frame the human ever receives (including its own join's state_sync) reflects it.
        table.state = new_game(_GAME_RULESET, seed)

        ws0.send_json(_msg("hello", {"client_version": "test"}))
        ws0.send_json(_msg("join", {"seat": 0, "name": "Dave"}, id_=_next_id()))
        ws0.send_json(_msg("ready", {}, id_=_next_id()))

        frames = _play_practice_game(ws0)

    # --- the game actually finished, through the real engine, not a rigged shortcut.
    assert table.state.phase == Phase.GAME_OVER
    game_end = frames[-1]
    assert game_end["t"] == "game_end"
    assert game_end["d"]["hand_no"] == 4  # bounded, per module docstring

    # --- the human's own join state_sync already shows every bot's real display name, not
    # null/empty -- proof M5 names are wired through to the human before the game even starts.
    join_sync = next(f for f in frames if f["t"] == "state_sync")
    assert join_sync["d"]["names"] == ["Dave", "FaanBot", "FaanBot", "FaanBot"]

    # --- the human acted on its own turns (at least one real discard from seat 0)...
    assert any(f["t"] == "discard" and f["d"]["seat"] == 0 for f in frames)
    # ...and so did every bot seat -- proof `_poke_bots()`/the real ProcessPoolExecutor path
    # actually drove them, not that the game happened to skip straight to GAME_OVER.
    for seat in (1, 2, 3):
        assert any(f["t"] == "discard" and f["d"]["seat"] == seat for f in frames), (
            f"seat {seat} (bot) never discarded -- bots did not actually play"
        )

    # --- practice-mode bot seats never get confused by disconnect/reconnect machinery: there
    # was no human behind them to disconnect, so status stays exactly "bot" throughout the whole
    # game, never flipped to "disconnected"/"autoplay"/"connected" by anything.
    for seat in (1, 2, 3):
        binding = table.seat_bindings[seat]
        assert binding is not None
        assert binding.status == "bot"
