import dataclasses
import json
import random

import pytest

from app.lessons.grade import answer_key
from app.lessons.model import Band, PuzzleKind
from app.lessons.pool import (
    POOL_PATH,
    Pool,
    PooledPuzzle,
    lesson_payload,
    load_pool,
    pick,
    pool_from_dict,
)
from bots.tiers import BotTier
from mahjong_core.engine import ENGINE_VERSION
from tests.lesson_payloads import assert_puzzle_payload
from tools.gen_lessons import check_catalog
from tools.mine_puzzles import mine, pool, pool_text

_POOL = load_pool()
_ALL = [p for puzzles in _POOL.puzzles.values() for p in puzzles]


def _key(pooled: PooledPuzzle) -> dict:
    return json.loads(json.dumps(dataclasses.asdict(answer_key(pooled.puzzle))))


def test_committed_pool_covers_every_kind_and_band_evenly() -> None:
    meta = json.loads(POOL_PATH.read_text())
    assert _POOL.engine_version == ENGINE_VERSION
    for kind in PuzzleKind:
        for band in Band:
            assert len(_POOL.puzzles[kind, band]) == meta["per_band"], (kind, band)


def test_committed_pool_is_the_tool_output() -> None:
    """Regenerated, not hand-edited: the file is exactly `pool_text` of its own contents."""
    text = POOL_PATH.read_text()
    payload = json.loads(text)
    meta = {k: v for k, v in payload.items() if k != "puzzles"}
    assert pool_text(payload["puzzles"], meta) == text


def test_pooled_ids_are_unique_lesson_ids() -> None:
    check_catalog([p.puzzle for p in _ALL])


@pytest.mark.parametrize("kind", list(PuzzleKind))
def test_every_pooled_key_is_the_engine_key(kind: PuzzleKind) -> None:
    for pooled in (p for p in _ALL if p.puzzle.kind == kind):
        assert dict(pooled.key) == _key(pooled), pooled.puzzle.id


def test_pick_keeps_kind_and_band() -> None:
    rng = random.Random(0)
    for kind in PuzzleKind:
        for band in Band:
            picked = pick(_POOL, kind, band, rng=rng)
            assert (picked.puzzle.kind, picked.puzzle.band) == (kind, band)


def test_pick_skips_excluded_ids_until_none_are_left() -> None:
    band = _POOL.puzzles[PuzzleKind.COUNT_FAAN, Band.ADVANCED]
    keep = band[7].puzzle.id
    others = {p.puzzle.id for p in band} - {keep}
    rng = random.Random(0)
    for _ in range(10):
        assert pick(_POOL, PuzzleKind.COUNT_FAAN, Band.ADVANCED, others, rng).puzzle.id == keep
    everything = others | {keep}
    assert (
        pick(_POOL, PuzzleKind.COUNT_FAAN, Band.ADVANCED, everything, rng).puzzle.id in everything
    )


def test_pick_without_a_band_draws_from_all_of_them() -> None:
    rng = random.Random(0)
    bands = {pick(_POOL, PuzzleKind.WINNING_TILES, None, rng=rng).puzzle.band for _ in range(60)}
    assert bands == set(Band)


def test_pick_from_an_empty_kind_raises() -> None:
    with pytest.raises(LookupError):
        pick(Pool(ENGINE_VERSION, {}), PuzzleKind.BEST_DISCARD, None)


def test_lesson_payload_is_a_lesson_file() -> None:
    pooled = _POOL.puzzles[PuzzleKind.SAFE_DISCARD, Band.BEGINNER][0]
    payload = lesson_payload(pooled)
    assert_puzzle_payload(payload)
    assert payload["id"] == pooled.puzzle.id
    assert payload["key"] == dict(pooled.key)
    assert lesson_payload(pooled) == payload


_TIERS = [BotTier.T0, BotTier.T1, BotTier.T2]


def test_pool_generation_is_deterministic_and_regrades() -> None:
    """One `FaanBot` game, as `test_mine_puzzles` mines, through `pool` and back."""
    records, _ = mine([7], 1, BotTier.T2, _TIERS)
    first = pool(records, 2)
    assert first == pool(records, 2)
    meta = {"engine_version": ENGINE_VERSION, "miner_tier": BotTier.T2, "per_band": 2}
    rebuilt = json.loads(pool_text(first, meta))
    assert rebuilt["puzzles"] == json.loads(json.dumps(first))
    for pooled in (p for ps in pool_from_dict(rebuilt).puzzles.values() for p in ps):
        assert dict(pooled.key) == _key(pooled), pooled.puzzle.id
