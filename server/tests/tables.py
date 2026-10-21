"""Create a table under a test-chosen id. `/ws` never creates one and `POST /tables` mints a
random id, so a WS test that names its own table goes through the live registry directly."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any

from fastapi.testclient import TestClient

from app import ws
from app.main import app
from app.table import Table
from mahjong_core.config import DEFAULT_RULESET, RuleSet


def create_table(
    client: TestClient, table_id: str, ruleset: RuleSet = DEFAULT_RULESET, **kwargs: Any
) -> Table:
    """`TableRegistry.get_or_create` on the app's event loop (it starts the table's task).
    `require_ready=True` like a `POST /tables` table unless overridden."""
    kwargs.setdefault("require_ready", True)
    assert client.portal is not None, "call inside `with TestClient(app) as client`"
    return client.portal.call(partial(ws.registry().get_or_create, table_id, ruleset, **kwargs))


@contextmanager
def table_client(
    table_id: str, ruleset: RuleSet = DEFAULT_RULESET, **kwargs: Any
) -> Iterator[TestClient]:
    """`with TestClient(app) as client` with `table_id` already created."""
    with TestClient(app) as client:
        create_table(client, table_id, ruleset, **kwargs)
        yield client
