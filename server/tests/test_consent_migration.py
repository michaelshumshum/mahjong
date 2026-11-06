"""Migration e4a7c2d9b815 clears consents given under the phase 3 draft wording
(docs/decisions/0028-user-account-schema.md "Phase 7")."""

from __future__ import annotations

import datetime as dt
import importlib.util
import uuid
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Engine, create_engine, insert, select

from app.accounts.routes import TRAINING_CONSENT_VERSION
from app.db.models import Base, User

_MIGRATION = (
    Path(__file__).parents[1] / "alembic/versions/e4a7c2d9b815_clear_draft_training_consents.py"
)
_AT = dt.datetime(2026, 11, 5, tzinfo=dt.UTC)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("clear_draft_consents", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed(engine: Engine, versions: dict[str, str | None]) -> dict[str, uuid.UUID]:
    ids = {name: uuid.uuid4() for name in versions}
    with engine.begin() as conn:
        conn.execute(
            insert(User.__table__),
            [
                {
                    "id": ids[name],
                    "display_name": name,
                    "training_consent_at": None if version is None else _AT,
                    "consent_version": version,
                }
                for name, version in versions.items()
            ],
        )
    return ids


def test_upgrade_clears_only_draft_consents() -> None:
    migration = _load()
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    _seed(
        engine,
        {"draft": migration.DRAFT_CONSENT_VERSION, "final": TRAINING_CONSENT_VERSION, "none": None},
    )

    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()

    with engine.connect() as conn:
        rows = conn.execute(
            select(User.display_name, User.training_consent_at, User.consent_version)
        ).all()
    consents = {name: (at is not None, version) for name, at, version in rows}
    assert consents == {
        "draft": (False, None),
        "final": (True, TRAINING_CONSENT_VERSION),
        "none": (False, None),
    }


def test_final_version_is_not_the_draft() -> None:
    assert TRAINING_CONSENT_VERSION != _load().DRAFT_CONSENT_VERSION
