"""pydantic -> TypeScript codegen for the wire protocol (docs/protocol.md §6).

Walks the pydantic model graph in app.protocol directly and emits TS — no JSON
Schema hop, because pydantic's tagged-union JSON Schema (`$defs` + `oneOf` +
`discriminator`) doesn't reliably survive a generic JSON-Schema->TS generator:
`const` tags get widened to `string` and narrowing breaks. See the docstring
in app/protocol.py and docs/protocol.md §6 for the full rationale.

Usage: uv run python tools/gen_protocol.py --ts-out <path> [--schema-out <path>]
"""

from __future__ import annotations

import argparse
import json
import types
import typing
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.protocol import AnyMessage, ClientMessage, Envelope, ServerMessage
from mahjong_core.config import CLIENT_RULE_BOUNDS
from mahjong_core.scoring.faan import CHICKEN_HAND_FAAN, CHICKEN_HAND_NAME
from mahjong_core.scoring.patterns import LIMIT_FAAN, PATTERNS
from mahjong_core.scoring.payout import POINTS_TABLES

# pydantic class name -> TS name. `Error` would shadow the global `Error`
# constructor if imported as-is in TS.
_TS_NAME_OVERRIDES = {"Error": "ErrorEvent"}

_GENERATED_HEADER = (
    "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
    "// Source of truth: server/app/protocol.py (docs/protocol.md §6).\n"
)


def ts_name(cls: type[BaseModel]) -> str:
    return _TS_NAME_OVERRIDES.get(cls.__name__, cls.__name__)


def _union_members(discriminated: Any) -> list[type[BaseModel]]:
    """Unwrap `Annotated[X | Y | ..., Field(discriminator=...)]` to [X, Y, ...]. Recurses into
    non-model members (`app/protocol.py`'s `AnyMessage = ClientMessage | ServerMessage`, a
    plain union of two *already*-discriminated unions -- the `discard` tag is reused across
    directions with different shapes, so one flat discriminator can't cover both; see that
    module's docstring) so callers always get a flat list of leaf message classes regardless
    of how many discriminated unions are nested."""
    if typing.get_origin(discriminated) is typing.Annotated:
        discriminated = typing.get_args(discriminated)[0]
    members = typing.get_args(discriminated)
    if not members:
        raise TypeError(f"gen_protocol: expected a Union, got {discriminated!r}")
    flat: list[type[BaseModel]] = []
    for member in members:
        if isinstance(member, type) and issubclass(member, BaseModel):
            flat.append(member)
        else:
            flat.extend(_union_members(member))
    return flat


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Every pydantic BaseModel reachable from a field annotation."""
    if isinstance(annotation, typing.TypeAliasType):
        return _nested_models(annotation.__value__)
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return _nested_models(typing.get_args(annotation)[0])
    if origin is typing.Literal:
        return []
    if origin in (types.UnionType, typing.Union):
        return [m for a in typing.get_args(annotation) for m in _nested_models(a)]
    if origin in (list, set, frozenset):
        return _nested_models(typing.get_args(annotation)[0])
    if origin is dict:
        key_t, value_t = typing.get_args(annotation)
        return _nested_models(key_t) + _nested_models(value_t)
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return [annotation]
    return []


type _NamedType = type[StrEnum] | typing.TypeAliasType


def _named_types(annotation: Any) -> list[_NamedType]:
    """Every StrEnum and `type X = ...` alias reachable from a field annotation, each emitted
    once as a named TS type."""
    if isinstance(annotation, typing.TypeAliasType):
        return [annotation, *_named_types(annotation.__value__)]
    origin = typing.get_origin(annotation)
    if origin is typing.Literal:
        return []
    if origin is not None:
        return [e for a in typing.get_args(annotation) for e in _named_types(a)]
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return [annotation]
    return []


def _render_named_type(named: _NamedType) -> str:
    if isinstance(named, typing.TypeAliasType):
        return f"export type {named.__name__} = {ts_type(named.__value__)};"
    return f"export type {named.__name__} = {' | '.join(_literal_ts(m.value) for m in named)};"


def _collect_models(roots: list[type[BaseModel]]) -> list[type[BaseModel]]:
    """BFS from `roots` over field types, so any future nested payload model
    is picked up automatically without touching this generator."""
    seen: set[str] = set()
    order: list[type[BaseModel]] = []
    queue = list(roots)
    while queue:
        cls = queue.pop(0)
        if cls.__name__ in seen:
            continue
        seen.add(cls.__name__)
        order.append(cls)
        for field in cls.model_fields.values():
            queue.extend(_nested_models(field.annotation))
    return order


def _literal_ts(value: Any) -> str:
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    raise TypeError(f"gen_protocol: unhandled Literal value {value!r}")


def ts_type(annotation: Any) -> str:
    if isinstance(annotation, typing.TypeAliasType):
        return annotation.__name__
    origin = typing.get_origin(annotation)
    if origin is typing.Annotated:
        return ts_type(typing.get_args(annotation)[0])
    if origin is typing.Literal:
        return " | ".join(_literal_ts(v) for v in typing.get_args(annotation))
    if origin in (types.UnionType, typing.Union):
        args = typing.get_args(annotation)
        present = [a for a in args if a is not type(None)]
        parts = [ts_type(a) for a in present]
        if len(present) != len(args):
            parts.append("null")
        return " | ".join(parts)
    if annotation is type(None):
        return "null"
    if annotation is Any:
        return "unknown"
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return annotation.__name__
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if origin in (list, set, frozenset):
        (item,) = typing.get_args(annotation)
        item_ts = ts_type(item)
        # `[]` binds tighter than `|` in TS -- `string | null[]` parses as `string | (null[])`, not
        # `(string | null)[]` -- parenthesize whenever the item itself rendered as a union.
        if typing.get_origin(item) in (types.UnionType, typing.Union):
            item_ts = f"({item_ts})"
        return f"{item_ts}[]"
    if origin is dict:
        key_t, value_t = typing.get_args(annotation)
        return f"Record<{ts_type(key_t)}, {ts_type(value_t)}>"
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return ts_name(annotation)
    raise TypeError(f"gen_protocol: no TS mapping for annotation {annotation!r}")


def _render_field(name: str, annotation: Any, required: bool) -> str:
    # a Literal field (`t`, `v`) is always sent and never omitted, regardless
    # of whether pydantic gives it a default for ergonomics on the Python side.
    if typing.get_origin(annotation) is typing.Literal or (
        typing.get_origin(annotation) is typing.Annotated
        and typing.get_origin(typing.get_args(annotation)[0]) is typing.Literal
    ):
        return f"\t{name}: {ts_type(annotation)};"
    marker = "" if required else "?"
    return f"\t{name}{marker}: {ts_type(annotation)};"


def _render_interface(cls: type[BaseModel], *, extends: type[BaseModel] | None) -> str:
    base_fields = set(extends.model_fields) if extends is not None else set()
    own_fields = {n: f for n, f in cls.model_fields.items() if n not in base_fields}
    heritage = f" extends {ts_name(extends)}" if extends is not None else ""
    lines = [f"export interface {ts_name(cls)}{heritage} {{"]
    lines += [_render_field(n, f.annotation, f.is_required()) for n, f in own_fields.items()]
    lines.append("}")
    return "\n".join(lines)


def render_ts(*, client_message: Any, server_message: Any, any_message: Any) -> str:
    client_members = _union_members(client_message)
    server_members = _union_members(server_message)
    any_members = _union_members(any_message)
    all_models = _collect_models([Envelope, *any_members])

    message_names = {m.__name__ for m in any_members}
    parts = [_GENERATED_HEADER.rstrip("\n")]

    named: dict[str, _NamedType] = {}
    for cls in all_models:
        for field in cls.model_fields.values():
            for t in _named_types(field.annotation):
                if named.setdefault(t.__name__, t) is not t:
                    raise TypeError(f"gen_protocol: two wire types named {t.__name__}")
    parts += [_render_named_type(t) for _, t in sorted(named.items())]

    for cls in all_models:
        extends = Envelope if cls.__name__ in message_names and cls is not Envelope else None
        parts.append(_render_interface(cls, extends=extends))

    parts.append(
        "/** Client -> server intents (docs/protocol.md §2). */\n"
        f"export type ClientMessage = {' | '.join(ts_name(m) for m in client_members)};"
    )
    parts.append(
        "/**\n"
        " * Server -> client events (docs/protocol.md §3). Keep the reducer's\n"
        " * switch over this type exhaustive (assertNever, protocol.assertNever.ts)\n"
        " * so a new member fails the build.\n"
        " */\n"
        f"export type ServerEvent = {' | '.join(ts_name(m) for m in server_members)};"
    )
    parts.append(
        "/** Mirrors protocol.py's AnyMessage — both directions, e.g. for a WS test harness. */\n"
        f"export type AnyMessage = {' | '.join(ts_name(m) for m in any_members)};"
    )
    return "\n\n".join(parts) + "\n"


def render_assert_never_fixture(*, server_message: Any) -> str:
    server_members = _union_members(server_message)
    cases = "\n".join(
        f"\t\tcase {_literal_ts(m.model_fields['t'].default)}:\n\t\t\treturn;"
        for m in server_members
    )
    return (
        "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
        "// Compile-time exhaustiveness check (docs/protocol.md §6): fails to\n"
        "// compile if ServerEvent gains a member this switch doesn't handle, or\n"
        "// if codegen ever regresses `t` from a literal to a widened `string`.\n"
        "import type { ServerEvent } from './protocol';\n\n"
        "function assertNever(x: never): never {\n"
        "\tthrow new Error(`unhandled: ${JSON.stringify(x)}`);\n"
        "}\n\n"
        "export function _assertExhaustive(e: ServerEvent): void {\n"
        "\tswitch (e.t) {\n"
        f"{cases}\n"
        "\t\tdefault:\n"
        "\t\t\tassertNever(e);\n"
        "\t}\n"
        "}\n"
    )


def _number_ts(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def render_constants() -> str:
    """Runtime values the client validates against before the server does (docs/protocol.md
    §6). A `.d.ts` can't carry values, so they get their own module."""
    bounds = "\n".join(
        f"\t{name}: {{ min: {_number_ts(lo)}, max: {_number_ts(hi)} }},"
        for name, (lo, hi) in CLIENT_RULE_BOUNDS.items()
    )
    patterns = "\n".join(
        f"\t{{ name: '{p.name}', handSet: '{p.hand_set.value}', faan: {p.faan}, "
        f"limit: {'true' if p.is_limit else 'false'} }},"
        for p in PATTERNS
    )
    points = "\n".join(
        f"\t{table.value}: [{', '.join(str(v) for v in values)}],"
        for table, values in POINTS_TABLES.items()
    )
    return (
        "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
        "// Source of truth: server/mahjong_core/config.py, server/mahjong_core/scoring/.\n\n"
        "/** Inclusive ranges for a client-supplied custom ruleset (docs/rules.md §10). */\n"
        f"export const CLIENT_RULE_BOUNDS = {{\n{bounds}\n}} as const;\n\n"
        "/** The largest faan a pattern can score, and so the largest faan override. */\n"
        f"export const LIMIT_FAAN = {LIMIT_FAAN};\n\n"
        "/** Every scored pattern at its default value, in registry order (docs/rules.md §7). */\n"
        f"export const FAAN_PATTERNS = [\n{patterns}\n] as const;\n\n"
        "/** 雞糊: not a registry pattern, scored by faan.py's own fallback. */\n"
        f"export const CHICKEN_HAND = {{ name: '{CHICKEN_HAND_NAME}', faan: {CHICKEN_HAND_FAAN} }} as const;\n\n"
        "/** Points per faan, indexed 0..LIMIT_FAAN (docs/rules.md §8). */\n"
        f"export const POINTS_TABLES = {{\n{points}\n}} as const;\n"
    )


def render_json_schema() -> dict[str, Any]:
    """Secondary, informational artifact only (docs/infra.md) — not what the
    TS above is generated from; see the module docstring for why."""
    return TypeAdapter(AnyMessage).json_schema()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    repo_root = Path(__file__).resolve().parents[2]
    parser.add_argument(
        "--ts-out",
        type=Path,
        default=repo_root / "web/src/lib/net/protocol.d.ts",
        help="output path for the generated TS types",
    )
    parser.add_argument(
        "--schema-out",
        type=Path,
        default=None,
        help="optional output path for the informational JSON Schema artifact",
    )
    args = parser.parse_args()

    ts = render_ts(
        client_message=ClientMessage, server_message=ServerMessage, any_message=AnyMessage
    )
    args.ts_out.parent.mkdir(parents=True, exist_ok=True)
    args.ts_out.write_text(ts)

    fixture_path = args.ts_out.parent / "protocol.assertNever.ts"
    fixture_path.write_text(render_assert_never_fixture(server_message=ServerMessage))

    constants_path = args.ts_out.parent / "protocol.constants.ts"
    constants_path.write_text(render_constants())

    if args.schema_out is not None:
        args.schema_out.parent.mkdir(parents=True, exist_ok=True)
        args.schema_out.write_text(json.dumps(render_json_schema(), indent=2) + "\n")

    print(f"wrote {args.ts_out}")
    print(f"wrote {fixture_path}")
    print(f"wrote {constants_path}")
    if args.schema_out is not None:
        print(f"wrote {args.schema_out}")


if __name__ == "__main__":
    main()
