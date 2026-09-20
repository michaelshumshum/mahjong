"""Live-UI regression test for the declare-button click bug: clicking "Win" / "Concealed
kong" / "Added kong" in the real (non-mock) table UI silently did nothing -- no WS frame, no
console output, no error.

Root cause (see `web/src/routes/table/[id]/+page.svelte`'s `.declare-actions button` block and
its comment): those buttons use `buttons.btn-primary`, whose `:active` state applies
`transform: translateY(3px)` (a "press down" effect). That transform moves the button out from
under a pointer that went down and is then released without moving -- exactly what a real click
does -- so the browser's `mouseup`/`click` hit-test lands on the button's own wrapper
`<div class="declare-actions">` instead of the button itself. Svelte 5's click delegation walks
up from the real event target looking for a handler; the wrapper div has none, so the button's
`onclick` never runs. No exception, no console output -- the click is just silently swallowed at
the DOM level. Confirmed via a real Chromium session: `document.addEventListener('click', ...,
true)` at the document root shows `click`'s target as the wrapper div, never the button.

A wire/reducer-level test can't catch this class of bug at all (it never touches a button), and
neither can a mock-mode UI test (`table.e2e.ts`) -- these three actions only render in the real,
non-mock table per `+page.svelte`'s own `declareOptions` derivation. This test drives a real
Playwright browser (Chromium, via `web/scripts/live-declare-click.mjs`, spawned as a subprocess
-- `web/`'s own `@playwright/test` devDependency is reused rather than adding Playwright as a
Python dependency) against a real backend, and asserts an actual `declare` frame goes out over
the wire when the button is clicked -- exactly the assertion "no console error" bugs like this
need, since asserting on UI state alone would have passed even with this bug present.

**Rigging the rare hand**: same technique `test_reconnect.py`'s `_rig_uncontested_state`/
`_rig_claim_window_state` use (`dataclasses.replace` on a freshly-dealt `GameState`), but this
needs the real backend serving on a real TCP port (a Playwright browser can't connect to
`TestClient`'s ASGI test transport), so the app runs via a real `uvicorn.Server` on a background
thread of *this* process instead -- `get_room()` then reaches the exact same in-memory `Room` the
browser's WS connections land in, the same way `test_reconnect.py`'s direct `room.state = ...`
assignment does against `TestClient`. The rig must land after all 4 browser pages have connected
(so the room exists) but before any of them joins (`Room.mark_ready`'s dealt-hand broadcast reads
`self.state` fresh, per its own docstring, so a rig before the last `ready` is picked up
verbatim) -- `live-declare-click.mjs` prints `PAGE_LOADED` at exactly that point and waits for a
`GO` line on its stdin before joining anyone.

Opt-in (spins up a real backend + real `vite dev` + a real browser -- same posture as
`web/src/routes/table/[id]/live.e2e.ts`, which this mirrors):

    RUN_LIVE_BACKEND_TESTS=1 uv run pytest -q server/tests/test_declare_actions_live_ui.py
"""

from __future__ import annotations

import dataclasses
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

import pytest
import uvicorn

from app.main import app
from app.ws import get_room
from mahjong_core.config import DEFAULT_RULESET
from mahjong_core.state import GameState, Phase, new_game
from mahjong_core.tiles import TileId, TileType, tile_ids_for_type

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_BACKEND_TESTS"),
    reason="opt-in: RUN_LIVE_BACKEND_TESTS=1 (spins up a real backend, vite dev, and a browser)",
)

SERVER_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = SERVER_DIR.parent / "web"
DRIVER_SCRIPT = WEB_DIR / "scripts" / "live-declare-click.mjs"

_ALL_TYPES_NO_MAN1 = [t for t in TileType if t != TileType.MAN_1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _with_seat(state: GameState, seat: int, **overrides: object) -> GameState:
    seats = list(state.seats)
    seats[seat] = dataclasses.replace(seats[seat], **overrides)  # type: ignore[arg-type]
    return dataclasses.replace(state, seats=tuple(seats))  # type: ignore[arg-type]


def _make_junk(used: set[TileId], n: int) -> tuple[TileId, ...]:
    """`n` single tiles, each a distinct type, none colliding with `used` (mutated in place) --
    cycling tile types (skipping MAN_1, reserved for the seat-0 kong below) so a single call
    never hands out a second copy of the same type, keeping every other seat's hand inert junk
    (no accidental pair/pung/kong of its own)."""
    tiles: list[TileId] = []
    i = 0
    while len(tiles) < n:
        t = _ALL_TYPES_NO_MAN1[i % len(_ALL_TYPES_NO_MAN1)]
        avail = [tid for tid in tile_ids_for_type(t) if tid not in used]
        if avail:
            used.add(avail[0])
            tiles.append(avail[0])
        i += 1
    return tuple(tiles)


def _rig_concealed_kong(seed: int) -> GameState:
    """Seat 0 on turn holding all 4 copies of 1m plus 10 inert singles (14 total, post-draw
    shape) -- `mahjong_core.melds.legal_self_melds` reads this as a legal concealed kong
    regardless of which tile was "just drawn" (its own docstring), so `legal_actions` genuinely
    includes `declare_concealed_kong` for this hand."""
    state = new_game(DEFAULT_RULESET, game_seed=seed)
    state = dataclasses.replace(state, phase=Phase.AWAIT_ACTION, turn=0, claim_window=None)
    used: set[TileId] = set(tile_ids_for_type(TileType.MAN_1))
    seat0 = (*tile_ids_for_type(TileType.MAN_1), *_make_junk(used, 10))
    state = _with_seat(state, 0, concealed=seat0, melds=(), discards=())
    for seat in (1, 2, 3):
        state = _with_seat(state, seat, concealed=_make_junk(used, 13))
    return state


def _wait_healthy(url: str, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=0.5)
            return
        except Exception as err:  # noqa: BLE001 - polling until it's up
            last_err = err
            time.sleep(0.2)
    raise TimeoutError(f"{url} never became healthy: {last_err}")


def test_concealed_kong_button_sends_declare_frame() -> None:
    room_id = "declare-live-ui-test"
    backend_port = _free_port()
    frontend_port = _free_port()

    config = uvicorn.Config(app, host="127.0.0.1", port=backend_port, log_level="warning")
    server = uvicorn.Server(config)
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()
    try:
        _wait_healthy(f"http://127.0.0.1:{backend_port}/healthz", timeout_s=20)

        frontend = subprocess.Popen(
            [
                "pnpm",
                "exec",
                "vite",
                "dev",
                "--port",
                str(frontend_port),
                "--strictPort",
            ],
            cwd=WEB_DIR,
            start_new_session=True,  # own process group -- `pnpm exec vite` forks a real vite
            # child that doesn't forward SIGTERM (`live.e2e.ts`'s own teardown comment), so
            # teardown below kills the whole group, not just this handle's own pid.
            env={**os.environ, "PUBLIC_WS_URL": f"ws://127.0.0.1:{backend_port}/ws"},
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            _wait_healthy(f"http://127.0.0.1:{frontend_port}", timeout_s=30)

            driver = subprocess.Popen(
                [
                    "node",
                    str(DRIVER_SCRIPT),
                    f"http://127.0.0.1:{frontend_port}",
                    room_id,
                    r"^Concealed kong 1m-1m-1m-1m$",
                ],
                cwd=WEB_DIR,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            try:
                assert driver.stdout is not None
                assert driver.stdin is not None

                result_line: str | None = None
                for line in driver.stdout:
                    line = line.rstrip("\n")
                    if line == "PAGE_LOADED":
                        room = get_room(room_id)
                        assert room is not None, "room not created by the browser's connections"
                        room.state = _rig_concealed_kong(seed=7)
                        driver.stdin.write("GO\n")
                        driver.stdin.flush()
                    elif line.startswith("RESULT "):
                        result_line = line[len("RESULT ") :]
                        break
                    else:
                        print(f"[driver] {line}", file=sys.stderr)

                driver.wait(timeout=15)
                assert driver.returncode == 0, "browser driver failed -- see captured output above"
                assert result_line is not None, "browser driver exited without a RESULT line"

                result = json.loads(result_line)
                frames = [json.loads(p) for p in result["framesSent"]]
                declare_frames = [f for f in frames if f.get("t") == "declare"]
                assert declare_frames, (
                    "clicking 'Concealed kong' sent no `declare` WS frame at all "
                    f"(frames observed: {frames})"
                )
                assert declare_frames[0]["d"]["kind"] == "concealed_kong"
                assert declare_frames[0]["d"]["tiles"] == [0, 1, 2, 3]
            finally:
                if driver.poll() is None:
                    driver.terminate()
                    driver.wait(timeout=5)
        finally:
            try:
                os.killpg(frontend.pid, 15)
            except ProcessLookupError:
                pass
            try:
                frontend.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(frontend.pid, 9)
                frontend.wait(timeout=5)
    finally:
        server.should_exit = True
        server_thread.join(timeout=10)
