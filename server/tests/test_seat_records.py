"""Seat records written with each finished game (docs/decisions/0028-user-account-schema.md
phase 1): `save_game_record(seats=, mode=)` and `Table._persist_game_record`."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Base, GameRecord, GameSeat
from app.db.records import SeatRecord, placements, save_game_record
from app.db.session import make_engine, make_session_factory
from app.table import Table
from app.table_types import SeatBinding
from bots.selfplay import play_game
from mahjong_core.config import RuleSet
from mahjong_core.engine import game_outcome
from mahjong_core.state import GameState

_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)
_GUESTS = [SeatRecord(kind="guest")] * 4


async def _finished_game(seed: int = 1) -> tuple[GameState, list]:
    state, actions = await play_game(seed=seed, ruleset=_BOUNDED_RULESET)
    return state, list(actions)


async def _seats(session: AsyncSession, game_id: int) -> list[GameSeat]:
    rows = await session.scalars(
        select(GameSeat).where(GameSeat.game_id == game_id).order_by(GameSeat.seat)
    )
    return list(rows.all())


@pytest.mark.parametrize(
    ("scores", "expected"),
    [
        ((30, 10, -10, -30), (1, 2, 3, 4)),
        ((-30, 10, 30, -10), (4, 2, 1, 3)),
        ((10, 10, -5, -15), (1, 1, 3, 4)),
        ((30, 0, 0, -30), (1, 2, 2, 4)),
        ((5, -5, -5, 5), (1, 3, 3, 1)),
        ((0, 0, 0, 0), (1, 1, 1, 1)),
    ],
)
def test_placements_share_the_better_place_on_ties(
    scores: tuple[int, int, int, int], expected: tuple[int, int, int, int]
) -> None:
    assert placements(scores) == expected


async def test_save_game_record_writes_four_seat_rows(session: AsyncSession) -> None:
    state, actions = await _finished_game()
    seats = [
        SeatRecord(kind="guest"),
        SeatRecord(kind="bot", bot_tier="T1"),
        SeatRecord(kind="bot", bot_tier="T2"),
        SeatRecord(kind="bot", bot_tier="ORACLE"),
    ]

    record = await save_game_record(session, state, actions, seats=seats, mode="practice")

    final_scores = game_outcome(state).final_scores
    rows = await _seats(session, record.id)
    assert [(r.seat, r.kind, r.user_id, r.bot_tier) for r in rows] == [
        (0, "guest", None, None),
        (1, "bot", None, "T1"),
        (2, "bot", None, "T2"),
        (3, "bot", None, "ORACLE"),
    ]
    assert tuple(r.final_score for r in rows) == final_scores
    assert tuple(r.placement for r in rows) == placements(final_scores)
    assert record.mode == "practice"


async def test_save_game_record_without_seats_writes_no_seat_rows(session: AsyncSession) -> None:
    state, actions = await _finished_game()
    record = await save_game_record(session, state, actions)
    assert await _seats(session, record.id) == []
    assert record.mode is None


async def test_save_game_record_rejects_wrong_seat_count(session: AsyncSession) -> None:
    state, actions = await _finished_game()
    with pytest.raises(ValueError, match="seats"):
        await save_game_record(session, state, actions, seats=_GUESTS[:3])


async def test_save_game_record_writes_game_and_seats_in_one_transaction(
    session: AsyncSession,
) -> None:
    state, actions = await _finished_game()
    bad = [*_GUESTS[:3], SeatRecord(kind="bot")]
    with pytest.raises(IntegrityError):
        await save_game_record(session, state, actions, seats=bad, mode="multiplayer")
    await session.rollback()
    assert await session.scalar(select(func.count()).select_from(GameRecord)) == 0


@pytest.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield make_session_factory(engine)
    await engine.dispose()


def _human(name: str, status: str = "connected") -> SeatBinding:
    return SeatBinding(
        session_id=f"sess-{name}",
        send=lambda seq, wire: None,
        name=name,
        status=status,  # type: ignore[arg-type]
    )


async def _persist(
    table: Table, factory: async_sessionmaker[AsyncSession]
) -> tuple[GameRecord, list[GameSeat]]:
    table.state, table.actions = await _finished_game()
    await table._persist_game_record()
    async with factory() as s:
        record = await s.scalar(select(GameRecord))
        assert record is not None
        return record, await _seats(s, record.id)


async def test_practice_table_records_bot_seats_with_their_tiers(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    table = Table(
        "practice-seats",
        _BOUNDED_RULESET,
        game_seed=1,
        session_factory=session_factory,
        practice=True,
        seat_bot_tiers={1: "T1", 2: "T2", 3: "ORACLE"},
    )
    table.seat_bindings[0] = _human("Alice")

    record, seats = await _persist(table, session_factory)

    assert record.mode == "practice"
    assert [(r.kind, r.user_id, r.bot_tier) for r in seats] == [
        ("guest", None, None),
        ("bot", None, "T1"),
        ("bot", None, "T2"),
        ("bot", None, "ORACLE"),
    ]
    final_scores = game_outcome(table.state).final_scores
    assert tuple(r.placement for r in seats) == placements(final_scores)


async def test_multiplayer_table_records_guests_and_keeps_an_autoplay_seat_a_guest(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    table = Table(
        "multiplayer-seats",
        _BOUNDED_RULESET,
        game_seed=1,
        session_factory=session_factory,
        bot_tier="ORACLE",
    )
    table.seat_bindings[0] = _human("Alice")
    table.seat_bindings[1] = _human("Bob", status="autoplay")
    table.seat_bindings[2] = _human("Carol", status="disconnected")
    table.seat_bindings[3] = _human("Dan")

    record, seats = await _persist(table, session_factory)

    assert record.mode == "multiplayer"
    assert record.players == ["Alice", "Bob", "Carol", "Dan"]
    assert [(r.kind, r.bot_tier) for r in seats] == [("guest", None)] * 4
