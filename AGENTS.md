# AGENTS.md

Browser-based multiplayer Hong Kong mahjong. Python/FastAPI server, SvelteKit (DOM + SCSS) client.
Reference docs live in `docs/` (index: `docs/README.md`); history, removed designs and deferred
work in `docs/decisions/` (ADR log).

## Context triggers

| Working on                                          | Read first                                                     |
| --------------------------------------------------- | -------------------------------------------------------------- |
| `core game logic, server mechanics`                 | [server/AGENTS.md](server/AGENTS.md), `docs/architecture.md`   |
| `game rules, scoring, RuleSet`                      | `docs/rules.md`                                                |
| `user interface, gameplay`                          | [web/AGENTS.md](web/AGENTS.md), `docs/frontend.md`             |
| `shared/protocol.schema.json`, `app/protocol.py`    | `docs/protocol.md`                                             |
| `bots and machine learning`                         | `docs/bots.md`, `docs/ml.md`                                   |
| `Dockerfile`, `docker-compose*`, `Makefile`, `mise.toml`, CI | `docs/infra.md`                                       |
| `*.spec.ts`, `*.test.ts`, writing/debugging tests   | `docs/testing.md`                                              |
| Scope, deferred features, "why isn't X built"       | `docs/decisions/README.md`, then the relevant ADR              |

Enforced for `server/`, `web/`, `shared/`, and infra files by
`.claude/hooks/enforce-routing-table.sh` (Edit/Write/Bash) — it denies the write until the
matching doc has shown up in this session (Read, or referenced in a Bash command/prompt).

Compliance: start every task by replying with `**Context read: <docs>**` listing the trigger docs
read this session, or `**Context read: N/A**` if no trigger applied.

## Local setup

Toolchain pinned in `mise.toml` (`mise install`). Native and Docker workflows, env vars, and native
equivalents of `make` targets: `docs/infra.md §2`.

## Session setup

MANDATORY, once per session, before touching any other tool: `activate_project`, then
`initial_instructions`. Skip only if Serena is unavailable/erroring — then fall back silently and
proceed.

## Tooling — required, not optional

- **Code nav/edit in `server/`, `web/`, `shared/`:** Serena MCP, always. `get_symbols_overview` >
  Read, `find_symbol` > Grep, `find_referencing_symbols` > Grep, `replace_symbol_body` > Edit,
  `rename_symbol` > manual rename. Grep/Read/Edit only for non-code files (`docs/`, config, JSON)
  or a one-line patch inside a function body.
- **Cross-session knowledge:** anything learned that isn't obvious from re-reading the code
  (a gotcha, a decision, a "why," a TODO for next session) goes in Serena memory — `write_memory`
  before ending the session, `list_memories`/`read_memory` at session start to load prior context.
- **Large/noisy output, `make test*`, and all `docker`/`docker-compose` commands:** context-mode
  (`ctx_execute`/`ctx_execute_file`/`ctx_batch_execute`), never raw Bash. No exceptions for "just
  checking status" — `docker ps`, `docker logs`, test runs, all of it goes through context-mode.

Fallback: if a tool above is unavailable, use the native equivalent and keep going — never block
the task on tooling. This is the only exception; otherwise these are not suggestions.

## Communication

- Terse. Lead with the answer.
- No preamble, no narration of what you're about to do, no recap of unchanged code.
- Report failures with the actual output. Don't claim something works unless it was run.

## Documentation

- Reference docs (`docs/*.md`) describe what the project _is_, not how it was decided. History,
  removed designs, measurement logs and deferred designs go in a decision record
  (`docs/decisions/NNNN-title.md`, see its README); link to it from the reference doc. `docs/ml.md`
  is the exception: it stays a plan with milestones while the agent is in progress.
- Sections are numbered and cited from code as `docs/<doc>.md §N`. Renumbering means updating
  every citation (`git grep 'docs/<doc>.md'`).
- Default to tables, lists and code blocks over prose.
- Rationale is allowed, and encouraged, where a decision is non-obvious or the reason it was made
  is itself load-bearing (why a constraint exists, why the obvious alternative doesn't work) —
  see `architecture.md §1`, `bots.md §4`, `ml.md §3` for the level to aim for. The rule
  being replaced ("no rationale beyond a clause") was cutting exactly this kind of content; don't
  gut a section to satisfy terseness.
- Update the relevant `docs/` file in the same change as the code.

## Testing

- `make test` before calling work done.
  - if the change is only relevant to `web`, run `make test-web` instead.
  - if the change is only relevant to `server`, run `make test-server` instead.
  - in most cases, one of the above is sufficient; if you have a reason to run all tests, do so.
- Local dev runs the fast suite only (`@pytest.mark.slow` — soaks, real-bot e2e, hypothesis runs
  — is excluded by default; `make test-server-slow` runs it explicitly). CI runs both, in
  parallel, on every push/PR (`docs/infra.md §9`) — nothing is ever silently skipped there.
- New behaviour gets a test in the same change; bugs get a failing regression test first.
- `mahjong_core` is pure — test it directly. No mocks, no I/O. Golden fixtures (the scoring hand
  suite, `tests/test_engine_trajectory_pin.py`'s seeded trajectory digests; `tests/replays/` is
  planned, not built) are data, not mocks, and are required — see `docs/testing.md §1`.
- Seeded and deterministic: a failing game is reproducible from `(ruleset, seed, actions)`.

## Comments

- Comment only deliberate decisions that aren't inferable from the code: a non-obvious
  constraint, a pinned version, a workaround, a rule that must not be relaxed.
- No comment restating what a name, type, or shape already says.
- Terse and lowercase. State the fact, not the reasoning, and skip the emphasis. Full sentences are not encouraged
- No banner or section-divider comments.

## Conventions

- Commits: `action(scope): description`. Small and single-purpose; don't mix refactor with
  behaviour change.
- Generated files are never hand-edited — run `make proto`.
- New dependencies need a reason beyond convenience.
