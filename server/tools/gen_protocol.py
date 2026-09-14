"""pydantic -> TypeScript codegen for the wire protocol (docs/02-protocol.md §6).

Walks the pydantic model graph in app.protocol directly and emits TS — no JSON
Schema hop, because pydantic's tagged-union JSON Schema (`$defs` + `oneOf` +
`discriminator`) doesn't reliably survive a generic JSON-Schema->TS generator:
`const` tags get widened to `string` and narrowing breaks. See the docstring
in app/protocol.py and docs/02-protocol.md §6 for the full rationale.

Usage: uv run python tools/gen_protocol.py --ts-out <path> [--schema-out <path>]
"""

from __future__ import annotations

import argparse
import json
import types
import typing
from pathlib import Path
from typing import Any

from pydantic import BaseModel, TypeAdapter

from app.protocol import AnyMessage, ClientMessage, Envelope, ServerMessage

# pydantic class name -> TS name. `Error` would shadow the global `Error`
# constructor if imported as-is in TS.
_TS_NAME_OVERRIDES = {"Error": "ErrorEvent"}

_GENERATED_HEADER = (
    "// GENERATED FILE — do not hand-edit. Run `make proto` to regenerate.\n"
    "// Source of truth: server/app/protocol.py (docs/02-protocol.md §6).\n"
)


def ts_name(cls: type[BaseModel]) -> str:
    return _TS_NAME_OVERRIDES.get(cls.__name__, cls.__name__)


def _union_members(discriminated: Any) -> list[type[BaseModel]]:
    """Unwrap `Annotated[X | Y | ..., Field(discriminator=...)]` to [X, Y, ...]."""
    if typing.get_origin(discriminated) is typing.Annotated:
        discriminated = typing.get_args(discriminated)[0]
    members = typing.get_args(discriminated)
    if not members:
        raise TypeError(f"gen_protocol: expected a Union, got {discriminated!r}")
    return list(members)


def _nested_models(annotation: Any) -> list[type[BaseModel]]:
    """Every pydantic BaseModel reachable from a field annotation."""
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
    if annotation is str:
        return "string"
    if annotation in (int, float):
        return "number"
    if annotation is bool:
        return "boolean"
    if origin in (list, set, frozenset):
        (item,) = typing.get_args(annotation)
        return f"{ts_type(item)}[]"
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

    for cls in all_models:
        extends = Envelope if cls.__name__ in message_names and cls is not Envelope else None
        parts.append(_render_interface(cls, extends=extends))

    parts.append(
        "/** Client -> server intents (docs/02-protocol.md §2). */\n"
        f"export type ClientMessage = {' | '.join(ts_name(m) for m in client_members)};"
    )
    parts.append(
        "/**\n"
        " * Server -> client events (docs/02-protocol.md §3). Keep the reducer's\n"
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
        "// Compile-time exhaustiveness check (docs/02-protocol.md §6): fails to\n"
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


def render_json_schema() -> dict[str, Any]:
    """Secondary, informational artifact only (docs/07-infra.md) — not what the
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

    if args.schema_out is not None:
        args.schema_out.parent.mkdir(parents=True, exist_ok=True)
        args.schema_out.write_text(json.dumps(render_json_schema(), indent=2) + "\n")

    print(f"wrote {args.ts_out}")
    print(f"wrote {fixture_path}")
    if args.schema_out is not None:
        print(f"wrote {args.schema_out}")


if __name__ == "__main__":
    main()
