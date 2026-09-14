# AGENTS.md

Browser-based multiplayer Hong Kong mahjong. Python/FastAPI server, SvelteKit (DOM/CSS) client.
Project outline lives in `docs/`.

## Context triggers

Read the listed files before touching matching paths.

| Working on | Read first |
| --- | --- |
| `server/**` | [server/AGENTS.md](server/AGENTS.md), `docs/00-architecture.md` |
| `web/**` | [web/AGENTS.md](web/AGENTS.md), `docs/03-frontend.md` |
| `mahjong_core/**`, rules, scoring, faan | `docs/01-rules-spec.md` |
| `protocol.py`, `shared/**`, WebSocket messages | `docs/02-protocol.md` |
| `bots/**` | `docs/04-bots.md`, `docs/06-ml.md` |
| `Dockerfile`, `docker-compose*`, `Makefile` | `docs/07-infra.md` |
| Milestones, scope, what to build next | `docs/05-roadmap.md` |

## Communication

- Terse. Lead with the answer.
- No preamble, no narration of what you're about to do, no recap of unchanged code.
- Report failures with the actual output. Don't claim something works unless it was run.

## Documentation

- Docs are outlines of what the project *is*, not records of how it was decided.
- Default to tables, lists and code blocks over prose.
- Rationale is allowed, and encouraged, where a decision is non-obvious or the reason it was made
  is itself load-bearing (why a constraint exists, why the obvious alternative doesn't work) —
  see `00-architecture.md §1`, `04-bots.md §4`, `06-ml.md §5` for the level to aim for. The rule
  being replaced ("no rationale beyond a clause") was cutting exactly this kind of content; don't
  gut a section to satisfy terseness.
- Update the relevant `docs/` file in the same change as the code.

## Testing

- `make test` before calling work done.
- New behaviour gets a test in the same change; bugs get a failing regression test first.
- `mahjong_core` is pure — test it directly. No mocks, no I/O. Golden fixtures (`tests/replays/`,
  the scoring hand suite) are data, not mocks, and are required — see `05-roadmap.md`.
- Seeded and deterministic: a failing game is reproducible from `(ruleset, seed, actions)`.

## Comments

- Comment only deliberate decisions that aren't inferable from the code: a non-obvious
  constraint, a pinned version, a workaround, a rule that must not be relaxed.
- No comment restating what a name, type, or shape already says.
- Terse and lowercase. State the fact, not the reasoning, and skip the emphasis.
- No banner or section-divider comments.

## Conventions

- Commits: `action(scope): description`. Small and single-purpose; don't mix refactor with
  behaviour change.
- Generated files are never hand-edited — run `make proto`.
- New dependencies need a reason beyond convenience.
