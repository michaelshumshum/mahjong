"""`GameRecord` persistence (docs/ml.md §2, docs/decisions/0018-milestone-plan.md M1).

Runs against SQLite (`aiosqlite`), not Postgres -- see the commit message / report for the
testing-strategy tradeoff. SQLite has no JSONB, so this only proves the model/save-function
logic and the action-log round trip; `app/db/models.py`'s `.with_variant(JSONB(), ...)` split
and the migration itself were separately applied-tested against a real `docker compose up -d
postgres` (see that report), which CI cannot do today (docs/infra.md §9: no Postgres
service in CI).
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import GameRecord
from app.db.records import get_game_record, is_replayable, save_game_record
from bots.random import RandomBot
from bots.selfplay import play_and_record_game, play_game
from mahjong_core.actions import (
    ClaimChow,
    ClaimKong,
    ClaimPung,
    ClaimWin,
    DeclareAddedKong,
    DeclareConcealedKong,
    DeclareWin,
    Discard,
    Pass,
    action_from_dict,
    action_to_dict,
)
from mahjong_core.config import RuleSet
from mahjong_core.engine import (
    ENGINE_VERSION,
    IllegalActionError,
    game_outcome,
    new_game,
    reduce,
    start_next_hand,
)
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import GameOutcome, Phase
from mahjong_core.tiles import TileId

_BOUNDED_RULESET = RuleSet(dealer_repeat_on_win=False, dealer_repeat_on_draw=False)


# --- action_to_dict / action_from_dict round trip --------------------------------------------


def test_action_round_trip_discard() -> None:
    action = Discard(tile_id=TileId(5))
    assert action_from_dict(action_to_dict(action)) == action


def test_action_round_trip_pass_and_claim_win() -> None:
    assert action_from_dict(action_to_dict(Pass(window_id=3, seat=2))) == Pass(window_id=3, seat=2)
    assert action_from_dict(action_to_dict(ClaimWin(window_id=3, seat=1))) == ClaimWin(
        window_id=3, seat=1
    )


def test_action_round_trip_claim_melds() -> None:
    chow = Meld(kind=MeldKind.CHOW, tiles=(TileId(0), TileId(4), TileId(8)), from_seat=0)
    action = ClaimChow(window_id=1, seat=1, meld=chow)
    assert action_from_dict(action_to_dict(action)) == action

    pung = Meld(kind=MeldKind.PUNG, tiles=(TileId(0), TileId(1), TileId(2)), from_seat=0)
    action2 = ClaimPung(window_id=1, seat=2, meld=pung)
    assert action_from_dict(action_to_dict(action2)) == action2

    kong = Meld(
        kind=MeldKind.EXPOSED_KONG, tiles=(TileId(0), TileId(1), TileId(2), TileId(3)), from_seat=0
    )
    action3 = ClaimKong(window_id=1, seat=3, meld=kong)
    assert action_from_dict(action_to_dict(action3)) == action3


def test_action_round_trip_self_declared_kongs_and_win() -> None:
    concealed_kong = Meld(
        kind=MeldKind.CONCEALED_KONG, tiles=(TileId(0), TileId(1), TileId(2), TileId(3))
    )
    action = DeclareConcealedKong(meld=concealed_kong)
    assert action_from_dict(action_to_dict(action)) == action

    added_kong = Meld(
        kind=MeldKind.ADDED_KONG, tiles=(TileId(36), TileId(37), TileId(38), TileId(39))
    )
    action2 = DeclareAddedKong(meld=added_kong)
    assert action_from_dict(action_to_dict(action2)) == action2

    assert action_from_dict(action_to_dict(DeclareWin())) == DeclareWin()


# --- GameOutcome round trip --------------------------------------------------------------------


def test_game_outcome_to_dict_from_dict_round_trip() -> None:
    outcome = GameOutcome(hand_count=4, final_scores=(10, -5, 0, -5))
    assert GameOutcome.from_dict(outcome.to_dict()) == outcome


def test_game_outcome_requires_game_over() -> None:
    state = new_game(_BOUNDED_RULESET, 1)
    with pytest.raises(IllegalActionError, match="GAME_OVER"):
        game_outcome(state)


# --- save_game_record / get_game_record / is_replayable ---------------------------------------


async def test_save_game_record_round_trips_a_finished_game(session: AsyncSession) -> None:
    state, actions = await play_game(seed=1, ruleset=_BOUNDED_RULESET)
    assert state.phase == Phase.GAME_OVER

    saved = await save_game_record(session, state, actions, players=["bot:RandomBot"] * 4)
    fetched = await get_game_record(session, saved.id)

    assert fetched is not None
    assert fetched.engine_version == ENGINE_VERSION
    assert fetched.ruleset == state.ruleset.to_dict()
    assert RuleSet.from_dict(fetched.ruleset) == state.ruleset
    assert fetched.seed == state.game_seed
    assert fetched.players == ["bot:RandomBot"] * 4
    assert fetched.result == game_outcome(state).to_dict()
    assert len(fetched.action_log) == len(actions)
    assert [action_from_dict(d) for d in fetched.action_log] == list(actions)
    assert fetched.created_at is not None


async def test_save_game_record_action_log_replays_to_the_same_outcome(
    session: AsyncSession,
) -> None:
    """The actual point of persisting the log: replaying it from `new_game(ruleset, seed)`
    must reproduce the same finished game (docs/architecture.md §3)."""
    state, actions = await play_game(seed=7, ruleset=_BOUNDED_RULESET)
    saved = await save_game_record(session, state, actions, players=["bot:RandomBot"] * 4)
    fetched = await get_game_record(session, saved.id)
    assert fetched is not None

    replay_state = new_game(RuleSet.from_dict(fetched.ruleset), fetched.seed)
    for data in fetched.action_log:
        while replay_state.phase == Phase.HAND_OVER:
            replay_state, _ = start_next_hand(replay_state)
        replay_state, _ = reduce(replay_state, action_from_dict(data))
    while replay_state.phase == Phase.HAND_OVER:
        replay_state, _ = start_next_hand(replay_state)

    assert replay_state.phase == Phase.GAME_OVER
    assert tuple(s.score for s in replay_state.seats) == tuple(s.score for s in state.seats)


async def test_save_game_record_rejects_unfinished_game(session: AsyncSession) -> None:
    state = new_game(_BOUNDED_RULESET, 1)
    with pytest.raises(ValueError, match="GAME_OVER"):
        await save_game_record(session, state, [])


async def test_save_game_record_rejects_wrong_player_count(session: AsyncSession) -> None:
    state, actions = await play_game(seed=1, ruleset=_BOUNDED_RULESET)
    with pytest.raises(ValueError, match="players"):
        await save_game_record(session, state, actions, players=["bot:RandomBot"] * 3)


def test_is_replayable_checks_engine_version_exactly() -> None:
    record = GameRecord(
        engine_version=ENGINE_VERSION,
        ruleset={},
        seed=1,
        action_log=[],
        players=[None, None, None, None],
        result={},
    )
    assert is_replayable(record)
    assert not is_replayable(record, current_version=f"{ENGINE_VERSION}-not-this")

    stale = GameRecord(
        engine_version="0.0.0-stale",
        ruleset={},
        seed=1,
        action_log=[],
        players=[None, None, None, None],
        result={},
    )
    assert not is_replayable(stale)


# --- bots/selfplay.py wiring: bot-only games actually get recorded end to end -----------------


async def test_play_and_record_game_persists_a_bot_only_game(session: AsyncSession) -> None:
    record = await play_and_record_game(session, seed=42, ruleset=_BOUNDED_RULESET)

    assert record.id is not None
    assert record.engine_version == ENGINE_VERSION
    assert record.players == ["bot:RandomBot"] * 4
    assert record.result["hand_count"] >= 1
    assert len(record.action_log) > 0

    fetched = await get_game_record(session, record.id)
    assert fetched is not None
    assert fetched.action_log == record.action_log


async def test_play_and_record_game_with_explicit_bots_labels_players(
    session: AsyncSession,
) -> None:
    bots = [RandomBot() for _ in range(4)]
    record = await play_and_record_game(session, seed=9, ruleset=_BOUNDED_RULESET, bots=bots)
    assert record.players == ["bot:RandomBot"] * 4
