import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.api_models import RandomLessonResponse
from app.lessons.catalog.mined import TRACKS
from app.lessons.model import Band, PuzzleKind
from app.lessons.pool import lesson_payload, load_pool
from app.main import app
from tests.lesson_payloads import assert_puzzle_payload
from tools.gen_lessons import OUT_DIR


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("band", list(Band))
@pytest.mark.parametrize("kind", list(PuzzleKind))
def test_returns_a_pooled_lesson_of_the_kind_and_band(
    client: TestClient, kind: PuzzleKind, band: Band
) -> None:
    response = client.get("/lessons/random", params={"kind": kind, "band": band})
    assert response.status_code == 200
    lesson = response.json()
    assert_puzzle_payload(lesson)
    RandomLessonResponse.model_validate(lesson)
    assert (lesson["kind"], lesson["band"], lesson["track"]) == (kind, band, TRACKS[kind])
    pooled = next(p for p in load_pool().puzzles[kind, band] if p.puzzle.id == lesson["id"])
    assert lesson == json.loads(json.dumps(lesson_payload(pooled)))


# the api container mounts server/ alone; ci runs natively with the whole repo
@pytest.mark.skipif(not OUT_DIR.is_dir(), reason="web/ is not mounted")
@pytest.mark.parametrize("kind", list(PuzzleKind))
def test_same_shape_as_the_generated_lesson_file(client: TestClient, kind: PuzzleKind) -> None:
    lesson = client.get("/lessons/random", params={"kind": kind}).json()
    bundled = json.loads((OUT_DIR / f"{TRACKS[kind]}-01.json").read_text())
    assert lesson.keys() == bundled.keys()
    assert lesson["key"].keys() == bundled["key"].keys()
    assert lesson["snapshot"].keys() == bundled["snapshot"].keys()
    assert lesson["snapshot"]["d"].keys() == bundled["snapshot"]["d"].keys()


def test_exclude_skips_recent_ids(client: TestClient) -> None:
    band = load_pool().puzzles[PuzzleKind.WINNING_TILES, Band.ADVANCED]
    keep = band[3].puzzle.id
    recent = [p.puzzle.id for p in band if p.puzzle.id != keep][:49]
    params = {"kind": "winning_tiles", "band": "advanced", "exclude": recent}
    ids = {client.get("/lessons/random", params=params).json()["id"] for _ in range(20)}
    assert not ids & set(recent)


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({}, id="no-kind"),
        pytest.param({"kind": "claim"}, id="unknown-kind"),
        pytest.param({"kind": "best_discard", "band": "expert"}, id="unknown-band"),
        pytest.param({"kind": "best_discard", "exclude": ["x"] * 51}, id="too-many-excluded"),
        pytest.param({"kind": "best_discard", "exclude": ["x" * 65]}, id="excluded-id-too-long"),
    ],
)
def test_bad_params_are_422(client: TestClient, params: dict) -> None:
    assert client.get("/lessons/random", params=params).status_code == 422


def test_rate_limited_per_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LESSON_RATE_LIMIT", "2")
    with TestClient(app, client=("203.0.113.7", 5000)) as client:
        for _ in range(2):
            assert client.get("/lessons/random", params={"kind": "count_faan"}).status_code == 200
        origin = {"Origin": "http://localhost:5173"}
        response = client.get("/lessons/random", params={"kind": "count_faan"}, headers=origin)
        assert response.status_code == 429
        assert "retry-after" in response.headers
        # the web reads the wait cross-origin
        assert "retry-after" in response.headers["access-control-expose-headers"].lower()


def test_cross_origin_reads_are_allowed_for_cors_origins(client: TestClient) -> None:
    response = client.get(
        "/lessons/random",
        params={"kind": "safe_discard"},
        headers={"Origin": "http://localhost:5173"},
    )
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
