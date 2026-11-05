"""A signed-in `join`: the WS handshake resolves the session cookie, the seat takes the account's
name and `user_id` (docs/architecture.md §2.1, docs/decisions/0028-user-account-schema.md)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.accounts.sessions import COOKIE_NAME
from app.ws import get_table
from tests.accounts import create_user, sign_in
from tests.tables import table_client
from tests.ws_frames import hello, msg, next_id


def _join(client: TestClient, table_id: str, name: str = "Typed") -> dict[str, Any]:
    """Join seat 0 and return its ack payload."""
    with client.websocket_connect(f"/ws?table={table_id}") as ws:
        ws.send_json(hello())
        ws.send_json(msg("join", {"seat": 0, "name": name}, id_=next_id()))
        frames = [ws.receive_json() for _ in range(3)]
    [ack] = [f for f in frames if f["t"] == "ack"]
    assert ack["d"]["ok"] is True
    seat_state = next(f for f in frames if f["t"] == "seat_state")
    return {"ack": ack["d"], "seat_state": seat_state["d"]}


def _binding(table_id: str) -> Any:
    table = get_table(table_id)
    assert table is not None
    return table.seat_bindings[0]


def test_a_signed_in_join_takes_the_account_name_and_id(accounts_db: str) -> None:
    user_id = create_user(accounts_db, display_name="Account Ann")
    table_id = f"acct-{uuid.uuid4()}"
    with table_client(table_id) as client:
        client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
        frames = _join(client, table_id, name="Typed Name")
        binding = _binding(table_id)
    assert (binding.name, binding.user_id) == ("Account Ann", user_id)
    assert frames["seat_state"]["name"] == "Account Ann"
    # nothing new on the wire: no account id or signed-in flag
    assert set(frames["seat_state"]) == {"seat", "status", "name"}
    assert str(user_id) not in str(frames)


def test_a_join_without_a_cookie_is_a_guest(accounts_db: str) -> None:
    table_id = f"acct-{uuid.uuid4()}"
    with table_client(table_id) as client:
        _join(client, table_id, name="Guesty")
        binding = _binding(table_id)
    assert (binding.name, binding.user_id) == ("Guesty", None)


@pytest.mark.parametrize("case", ["bad-cookie", "flag-off", "disabled"])
def test_an_unusable_cookie_falls_back_to_a_guest(
    accounts_db: str, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    columns: dict[str, Any] = {"display_name": "Account Ann"}
    if case == "disabled":
        columns["disabled_at"] = dt.datetime.now(dt.UTC)
    token = sign_in(accounts_db, create_user(accounts_db, **columns))
    if case == "bad-cookie":
        token = "forged"
    if case == "flag-off":
        monkeypatch.delenv("ACCOUNTS_ENABLED")
    table_id = f"acct-{uuid.uuid4()}"
    with table_client(table_id) as client:
        client.cookies.set(COOKIE_NAME, token)
        _join(client, table_id, name="Guesty")
        binding = _binding(table_id)
    assert (binding.name, binding.user_id) == ("Guesty", None)


def test_an_account_takes_one_seat_per_table(accounts_db: str) -> None:
    user_id = create_user(accounts_db, display_name="Account Ann")
    table_id = f"acct-{uuid.uuid4()}"
    with table_client(table_id) as client:
        client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
        with client.websocket_connect(f"/ws?table={table_id}") as first:
            first.send_json(hello())
            first.send_json(msg("join", {"seat": 0}, id_=next_id()))
            secret = next(f for f in _frames(first, 3) if f["t"] == "ack")["d"]["reconnect_secret"]
            # a second tab: a fresh session id, same account
            with client.websocket_connect(f"/ws?table={table_id}") as second:
                second.send_json(hello())
                second.send_json(msg("join", {"seat": 1}, id_=next_id()))
                ack = second.receive_json()
        table = get_table(table_id)
        assert table is not None
        assert table.seat_bindings[1] is None
        # the account's own seat is still reclaimable by its secret
        with client.websocket_connect(f"/ws?table={table_id}") as again:
            again.send_json(hello(seat=0, secret=secret, last_seq=0))
            reclaimed = again.receive_json()
    assert ack["t"] == "ack"
    assert (ack["d"]["ok"], ack["d"]["error"]) == (False, "already_seated")
    assert reclaimed["t"] != "error"


def test_two_guests_may_share_a_table(accounts_db: str) -> None:
    table_id = f"acct-{uuid.uuid4()}"
    with (
        table_client(table_id) as client,
        client.websocket_connect(f"/ws?table={table_id}") as first,
    ):
        first.send_json(hello())
        first.send_json(msg("join", {"seat": 0}, id_=next_id()))
        _frames(first, 3)
        with client.websocket_connect(f"/ws?table={table_id}") as second:
            second.send_json(hello())
            second.send_json(msg("join", {"seat": 1}, id_=next_id()))
            frames = _frames(second, 3)
    assert next(f for f in frames if f["t"] == "ack")["d"]["ok"] is True


def _frames(ws: Any, n: int) -> list[dict[str, Any]]:
    return [ws.receive_json() for _ in range(n)]


def test_a_reconnect_keeps_the_account(accounts_db: str) -> None:
    user_id = create_user(accounts_db, display_name="Account Ann")
    table_id = f"acct-{uuid.uuid4()}"
    with table_client(table_id) as client:
        client.cookies.set(COOKIE_NAME, sign_in(accounts_db, user_id))
        secret = _join(client, table_id)["ack"]["reconnect_secret"]
        client.cookies.clear()
        with client.websocket_connect(f"/ws?table={table_id}") as ws:
            ws.send_json(hello(seat=0, secret=secret, last_seq=0))
            ws.receive_json()
        binding = _binding(table_id)
    assert (binding.name, binding.user_id) == ("Account Ann", user_id)
