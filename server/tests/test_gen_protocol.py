import re
from typing import Any, get_args

from app.protocol import AnyMessage, ClientMessage, Seat, ServerMessage
from app.table_types import SeatStatus, WireSeatStatus
from app.views import CLAIM_KIND_WIRE, ClaimChoice, WindName
from bots.tiers import BotTier
from mahjong_core.state import Wind
from tools.gen_protocol import (
    _union_members,
    render_assert_never_fixture,
    render_ts,
    ts_name,
    ts_type,
)


def _kwargs() -> dict[str, Any]:
    return {
        "client_message": ClientMessage,
        "server_message": ServerMessage,
        "any_message": AnyMessage,
    }


def test_every_message_type_gets_an_interface() -> None:
    ts = render_ts(**_kwargs())
    for cls in _union_members(AnyMessage):
        assert f"export interface {ts_name(cls)} " in ts, ts_name(cls)


def test_error_renamed_to_avoid_shadowing_global() -> None:
    ts = render_ts(**_kwargs())
    assert "export interface Error " not in ts
    assert "export interface ErrorEvent " in ts


def test_client_and_server_unions_match_protocol_py_split() -> None:
    ts = render_ts(**_kwargs())
    client_names = {ts_name(c) for c in _union_members(ClientMessage)}
    server_names = {ts_name(c) for c in _union_members(ServerMessage)}

    client_line = next(
        line for line in ts.splitlines() if line.startswith("export type ClientMessage")
    )
    server_line = next(
        line for line in ts.splitlines() if line.startswith("export type ServerEvent")
    )

    assert client_names == {m.strip() for m in client_line.split("=")[1].rstrip(";").split("|")}
    assert server_names == {m.strip() for m in server_line.split("=")[1].rstrip(";").split("|")}


def test_output_braces_are_balanced() -> None:
    ts = render_ts(**_kwargs())
    assert ts.count("{") == ts.count("}") > 0
    # every interface parses as `export interface Name [extends Base] { ...fields... }`
    assert len(re.findall(r"export interface \w+(?: extends \w+)? \{[^}]*\}", ts)) == len(
        re.findall(r"^export interface ", ts, flags=re.MULTILINE)
    )


def test_literal_t_field_is_never_optional() -> None:
    ts = render_ts(**_kwargs())
    for cls in _union_members(AnyMessage):
        t_value = cls.model_fields["t"].default
        assert f"\tt: '{t_value}';" in ts


def test_list_of_optional_union_is_parenthesized() -> None:
    """`[]` binds tighter than `|` in TS, so `list[str | None]` must render as
    `(string | null)[]`, never the silently-wrong `string | null[]` (`state_sync.names`, M5) --
    regression for the bug this field's codegen found."""
    assert ts_type(list[str | None]) == "(string | null)[]"


def test_assert_never_fixture_covers_every_server_event() -> None:
    fixture = render_assert_never_fixture(server_message=ServerMessage)
    server_members = _union_members(ServerMessage)
    for cls in server_members:
        t_value = cls.model_fields["t"].default
        assert f"case '{t_value}':" in fixture
    assert "assertNever(e)" in fixture
    assert fixture.count("case '") == len(server_members)


def test_str_enum_field_emits_one_named_union() -> None:
    ts = render_ts(**_kwargs())
    union = " | ".join(f"'{t.value}'" for t in BotTier)
    assert ts.count("export type BotTier =") == 1
    assert f"export type BotTier = {union};" in ts
    assert ts_type(list[BotTier | None]) == "(BotTier | null)[]"


def test_type_alias_field_emits_one_named_type() -> None:
    ts = render_ts(**_kwargs())
    assert ts.count("export type Seat =") == 1
    assert "export type Seat = 0 | 1 | 2 | 3;" in ts
    assert "export type WireSeatStatus = 'connected' | " in ts
    assert ts_type(Seat | None) == "Seat | null"
    assert ts_type(list[WireSeatStatus]) == "WireSeatStatus[]"


def test_wire_aliases_match_their_server_sources() -> None:
    assert get_args(WindName.__value__) == tuple(w.name for w in Wind)
    assert set(CLAIM_KIND_WIRE.values()) < set(get_args(ClaimChoice.__value__))
    assert set(get_args(SeatStatus.__value__)) | {"empty"} == set(
        get_args(WireSeatStatus.__value__)
    )
