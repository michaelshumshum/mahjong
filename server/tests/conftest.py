"""`--games` CLI option for the self-play soak test (docs/05-roadmap.md §2, Makefile's
`selfplay` target: `pytest -q -m slow -k selfplay --games=$${N:-10000}`)."""

from __future__ import annotations

import pytest


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
