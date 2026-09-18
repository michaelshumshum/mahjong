"""`--games` CLI option for the self-play soak test (docs/05-roadmap.md §2, Makefile's
`selfplay` target: `pytest -q -m slow -k selfplay --games=$${N:-10000}`).

Also sets a session-wide default for `SHUTDOWN_GRACE_SECONDS` (docs/00-architecture.md §8.1,
`app/main.py`'s `lifespan`): every `TestClient(app)` context in the WS-integration tests
(`test_ws_gameplay.py`, `test_reconnect.py`, `test_disconnect_bot_handover.py`, ...) runs the
exact same ASGI shutdown-phase code a real SIGTERM does when its `with` block exits, and most of
those rooms are still mid-game (not `Phase.GAME_OVER`) at that point -- the real default
(90s) would make every one of those tests hang for up to 90 real seconds on teardown.
`setdefault` here (module-level, evaluated once at collection, before any test or `app.main`
import runs) is this codebase's usual test-time-control pattern applied via env var rather than
a `RuleSet` field -- same idea `test_disconnect_bot_handover.py`'s `disconnect_grace_seconds=0`
already established, just process-level rather than per-game. A test that actually exercises the
grace window (`test_shutdown.py`) overrides it per-call via `begin_shutdown(grace_seconds=...)`
directly rather than relying on this env var.

Same reasoning zeroes `BOT_THINK_MIN_SECONDS`/`BOT_THINK_MAX_SECONDS` (`app/room.py`'s
`_await_bot_job` humanising think delay, docs/04-bots.md §1): real over the wire in the WS-
integration tests, a real bot tier answers in milliseconds, but every `_await_bot_job` still
sleeps 0.4-1.4s per decision by default -- multiplied across a whole hand's worth of bot turns,
that's real minutes added to the suite for a delay that exists purely for a human watching the
table, not for test correctness. No test currently asserts on the delay itself, so zeroing it here
is safe."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("SHUTDOWN_GRACE_SECONDS", "0")
os.environ.setdefault("BOT_THINK_MIN_SECONDS", "0")
os.environ.setdefault("BOT_THINK_MAX_SECONDS", "0")


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--games",
        action="store",
        type=int,
        default=10000,
        help="number of games for the self-play soak test (default: 10000)",
    )


@pytest.fixture
def games(request: pytest.FixtureRequest) -> int:
    return int(request.config.getoption("--games"))
