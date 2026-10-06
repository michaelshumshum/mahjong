# Documentation

Reference docs describe the system as it is. History, removed designs and deferred work live in
the [decision log](decisions/README.md).

| Doc | Covers |
| --- | --- |
| [architecture.md](architecture.md) | process model, table actor, claim window, redaction, failure handling, anti-cheat |
| [rules.md](rules.md) | tiles, turn state machine, claim priority, faan table, payments, `RuleSet`, edge cases |
| [protocol.md](protocol.md) | WebSocket envelope, message catalog, reconnect/resync, codegen, HTTP endpoints |
| [frontend.md](frontend.md) | rendering, layout, interaction, client state, routes, assets, a11y and i18n |
| [bots.md](bots.md) | bot interface, tiers, shanten/ukeire, value planning, safety, arena, `ORACLE` |
| [ml.md](ml.md) | self-play RL agent — in progress, kept as a plan with milestones |
| [rl-learnings.md](rl-learnings.md) | RL training record: curriculum progress, training metrics, evaluation over training, observed agent behaviour, findings for future runs |
| [infra.md](infra.md) | repo layout, toolchain, local dev, Docker, database, deployment, CI |
| [testing.md](testing.md) | test strategy per layer, Vitest and pytest gotchas |
| [decisions/](decisions/README.md) | ADR log: accepted, deferred, rejected and historical decisions |

Conventions: sections are numbered and cited from code as `docs/<doc>.md §N`; keep numbering
stable, and update the doc in the same change as the code it describes.
