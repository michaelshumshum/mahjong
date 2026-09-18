import re

from app.protocol import AnyMessage, ClientMessage, ServerMessage
from tools.gen_protocol import (
    _union_members,
    render_assert_never_fixture,
    render_ts,
    ts_name,
    ts_type,
)


def _kwargs() -> dict:
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
