"""`game_players` and `games.mode` constraints (docs/decisions/0028-user-account-schema.md
"Guests and bots in game_players")."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord, GameSeat, User


async def _game(session: AsyncSession, **overrides: Any) -> GameRecord:
    columns: dict[str, Any] = {
        "engine_version": "test",
        "ruleset": {},
        "seed": 1,
        "action_log": [],
        "players": [None, None, None, None],
        "result": {},
    }
    record = GameRecord(**(columns | overrides))
    session.add(record)
    await session.commit()
    return record


def _seat(game_id: int, **overrides: Any) -> GameSeat:
    columns: dict[str, Any] = {
        "game_id": game_id,
        "seat": 0,
        "kind": "guest",
        "user_id": None,
        "bot_tier": None,
        "final_score": 0,
        "placement": 1,
    }
    return GameSeat(**(columns | overrides))


async def _rejects(session: AsyncSession, row: Any) -> None:
    session.add(row)
    with pytest.raises(IntegrityError):
        await session.commit()
    await session.rollback()


async def test_each_kind_round_trips(session: AsyncSession) -> None:
    game = await _game(session, mode="multiplayer")
    user = User(display_name="Ann")
    session.add(user)
    await session.commit()
    user_id = user.id
    session.add_all(
        [
            _seat(game.id, seat=0, kind="user", user_id=user_id, final_score=40, placement=1),
            _seat(game.id, seat=1, kind="user", final_score=0, placement=2),
            _seat(game.id, seat=2, kind="guest", final_score=0, placement=2),
            _seat(game.id, seat=3, kind="bot", bot_tier="T2", final_score=-40, placement=4),
        ]
    )
    await session.commit()

    rows = (await session.scalars(select(GameSeat).where(GameSeat.game_id == game.id))).all()
    assert [
        (r.seat, r.kind, r.user_id, r.bot_tier) for r in sorted(rows, key=lambda r: r.seat)
    ] == [
        (0, "user", user_id, None),
        (1, "user", None, None),
        (2, "guest", None, None),
        (3, "bot", None, "T2"),
    ]


@pytest.mark.parametrize("seat", [-1, 4])
async def test_rejects_a_seat_out_of_range(session: AsyncSession, seat: int) -> None:
    game = await _game(session)
    await _rejects(session, _seat(game.id, seat=seat))


async def test_rejects_an_unknown_kind(session: AsyncSession) -> None:
    game = await _game(session)
    await _rejects(session, _seat(game.id, kind="robot"))


@pytest.mark.parametrize(
    "overrides",
    [
        {"kind": "guest", "user_id": uuid.uuid4()},
        {"kind": "guest", "bot_tier": "T2"},
        {"kind": "bot", "bot_tier": None},
        {"kind": "bot", "bot_tier": "T2", "user_id": uuid.uuid4()},
        {"kind": "user", "user_id": uuid.uuid4(), "bot_tier": "T2"},
    ],
    ids=["guest-id", "guest-tier", "bot-no-tier", "bot-id", "user-tier"],
)
async def test_rejects_a_bad_kind_pairing(session: AsyncSession, overrides: dict[str, Any]) -> None:
    game = await _game(session)
    await _rejects(session, _seat(game.id, **overrides))


@pytest.mark.parametrize("placement", [0, 5])
async def test_rejects_a_placement_out_of_range(session: AsyncSession, placement: int) -> None:
    game = await _game(session)
    await _rejects(session, _seat(game.id, placement=placement))


async def test_rejects_a_duplicate_seat(session: AsyncSession) -> None:
    game = await _game(session)
    session.add(_seat(game.id))
    await session.commit()
    session.expunge_all()
    await _rejects(session, _seat(game.id))


async def test_rejects_a_seat_for_a_missing_game(session: AsyncSession) -> None:
    await _rejects(session, _seat(999))


async def test_deleting_a_game_cascades_to_its_seats(session: AsyncSession) -> None:
    game = await _game(session)
    session.add_all([_seat(game.id, seat=s) for s in range(4)])
    await session.commit()

    await session.execute(delete(GameRecord).where(GameRecord.id == game.id))
    await session.commit()

    assert (await session.scalars(select(GameSeat))).all() == []


@pytest.mark.parametrize("mode", ["practice", "multiplayer", None])
async def test_games_mode_accepts_known_values(session: AsyncSession, mode: str | None) -> None:
    game = await _game(session, mode=mode)
    assert (await session.get(GameRecord, game.id)).mode == mode  # type: ignore[union-attr]


async def test_games_mode_rejects_an_unknown_value(session: AsyncSession) -> None:
    await _rejects(
        session,
        GameRecord(
            engine_version="test",
            ruleset={},
            seed=1,
            action_log=[],
            players=[None, None, None, None],
            result={},
            mode="ranked",
        ),
    )


async def test_user_index_is_partial_and_newest_first(session: AsyncSession) -> None:
    [ddl] = (
        await session.scalars(
            text(
                "SELECT sql FROM sqlite_master"
                " WHERE type = 'index' AND tbl_name = 'game_players' AND sql IS NOT NULL"
            )
        )
    ).all()
    assert "(user_id, game_id DESC)" in ddl
    assert ddl.endswith("WHERE user_id IS NOT NULL")
