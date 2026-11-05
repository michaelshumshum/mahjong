"""`GET /me/games` (docs/protocol.md §10 "Accounts")."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.accounts.routes import MAX_GAMES_PAGE
from app.accounts.sessions import COOKIE_NAME
from app.db.models import GameMode, GameRecord, GameSeat, SeatKind
from app.main import app
from tests.accounts import create_user, run_db, sign_in

_SCORES = [10, 40, -20, -30]
_PLACES = [2, 1, 3, 4]


def _signed_in(client: TestClient, accounts_db: str) -> uuid.UUID:
    user_id = create_user(accounts_db)
    client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
    return user_id


def _seed_game(
    accounts_db: str,
    seats: list[tuple[SeatKind, uuid.UUID | None, str | None]],
    *,
    mode: GameMode | None = "multiplayer",
    players: list[str | None] | None = None,
) -> int:
    """One saved game; `seats[s]` is `(kind, user_id, bot_tier)`."""

    async def work(db: AsyncSession) -> int:
        game = GameRecord(
            engine_version="test",
            ruleset={},
            seed=7,
            action_log=[],
            players=players or ["Bob", "Ann", None, "Cy"],
            result={"hand_count": 5, "final_scores": _SCORES},
            mode=mode,
        )
        db.add(game)
        await db.flush()
        db.add_all(
            GameSeat(
                game_id=game.id,
                seat=s,
                kind=kind,
                user_id=user_id,
                bot_tier=tier,
                final_score=_SCORES[s],
                placement=_PLACES[s],
            )
            for s, (kind, user_id, tier) in enumerate(seats)
        )
        await db.commit()
        return game.id

    return run_db(accounts_db, work)


def _mine_at_1(user_id: uuid.UUID, **kw: Any) -> int:
    return _seed_game(
        kw.pop("db"),
        [
            ("guest", None, None),
            ("user", user_id, None),
            ("bot", None, "T3"),
            ("guest", None, None),
        ],
        **kw,
    )


def test_games_need_a_session(accounts_db: str) -> None:
    with TestClient(app) as client:
        assert client.get("/me/games").status_code == 401


def test_games_404_while_the_flag_is_off(accounts_db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ACCOUNTS_ENABLED")
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.get("/me/games").status_code == 404


def test_games_list_the_callers_seat_and_the_other_three(accounts_db: str) -> None:
    other = create_user(accounts_db, display_name="Cy")
    with TestClient(app) as client:
        me = _signed_in(client, accounts_db)
        game_id = _seed_game(
            accounts_db,
            [
                ("user", None, None),
                ("user", me, None),
                ("bot", None, "T3"),
                ("user", other, None),
            ],
            players=["Gone", "Ann", None, "Cy"],
        )
        body = client.get("/me/games").json()
    assert body["next"] is None
    [game] = body["games"]
    assert game["game_id"] == game_id
    assert game["mode"] == "multiplayer"
    assert game["hand_count"] == 5
    assert (game["seat"], game["placement"], game["final_score"]) == (1, 1, 40)
    assert game["created_at"]
    # a deleted account is a name only; no seat carries a user id
    assert game["others"] == [
        {"seat": 0, "kind": "user", "name": "Gone", "bot_tier": None},
        {"seat": 2, "kind": "bot", "name": None, "bot_tier": "T3"},
        {"seat": 3, "kind": "user", "name": "Cy", "bot_tier": None},
    ]
    assert str(other) not in str(body)


def test_games_hold_only_the_callers_seats(accounts_db: str) -> None:
    other = create_user(accounts_db, display_name="Cy")
    with TestClient(app) as client:
        me = _signed_in(client, accounts_db)
        mine = _mine_at_1(me, db=accounts_db)
        _mine_at_1(other, db=accounts_db)
        _seed_game(accounts_db, [("guest", None, None)] * 4)
        games = client.get("/me/games").json()["games"]
    assert [g["game_id"] for g in games] == [mine]


def test_games_page_newest_first_by_cursor(accounts_db: str) -> None:
    with TestClient(app) as client:
        me = _signed_in(client, accounts_db)
        ids = [_mine_at_1(me, db=accounts_db) for _ in range(5)]
        first = client.get("/me/games", params={"limit": 2}).json()
        second = client.get("/me/games", params={"limit": 2, "before": first["next"]}).json()
        last = client.get("/me/games", params={"limit": 2, "before": second["next"]}).json()
        exact = client.get("/me/games", params={"limit": 5}).json()
    assert [g["game_id"] for g in first["games"]] == [ids[4], ids[3]]
    assert first["next"] == ids[3]
    assert [g["game_id"] for g in second["games"]] == [ids[2], ids[1]]
    assert [g["game_id"] for g in last["games"]] == [ids[0]]
    assert last["next"] is None
    # a page that ends exactly on the last game has no cursor
    assert len(exact["games"]) == 5
    assert exact["next"] is None


@pytest.mark.parametrize("limit", [0, MAX_GAMES_PAGE + 1])
def test_games_reject_a_limit_out_of_range(accounts_db: str, limit: int) -> None:
    with TestClient(app) as client:
        _signed_in(client, accounts_db)
        assert client.get("/me/games", params={"limit": limit}).status_code == 422


def test_games_filter_by_mode(accounts_db: str) -> None:
    with TestClient(app) as client:
        me = _signed_in(client, accounts_db)
        practice = _mine_at_1(me, db=accounts_db, mode="practice")
        multi = _mine_at_1(me, db=accounts_db, mode="multiplayer")
        unknown = _mine_at_1(me, db=accounts_db, mode=None)
        by_mode = {
            mode: [g["game_id"] for g in client.get("/me/games", params=params).json()["games"]]
            for mode, params in [
                ("practice", {"mode": "practice"}),
                ("multiplayer", {"mode": "multiplayer"}),
                ("all", {}),
            ]
        }
        bad = client.get("/me/games", params={"mode": "ranked"}).status_code
    assert by_mode == {
        "practice": [practice],
        "multiplayer": [multi],
        "all": [unknown, multi, practice],
    }
    assert bad == 422
