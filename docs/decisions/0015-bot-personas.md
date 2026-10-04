# 0015. Bot personas

- **Status:** Deferred (play-style half built 2026-09-28)
- **Date:** 2026-09-14

## Context

A bot with a **persona** — a name, an avatar, a play-style bias (aggressive / defensive /
flush-lover) and a think-time distribution — is more memorable than one that's marginally more
optimal. The play-style bias is the same mechanism [ml.md §12](../ml.md) needs for mixed-table
evaluation.

## Built

`bots/faanbot.py`'s `WeightProfile` with `BASELINE`/`AGGRESSIVE`/`DEFENSIVE`/`FLUSH_CHASING`,
registered in `bots/arena.py`'s `BOT_REGISTRY` as `FaanBotAggressive`/`FaanBotDefensive`/
`FaanBotFlushChasing` — used for training variety.

## Not built

- A persona **name** (bot seats currently draw a random display name, unrelated to tier) and
  **avatar**.
- A per-persona **think-time distribution** — the humanising delay is uniform per decision
  ([bots.md §1](../bots.md)).
- Live-table selection. A weight profile isn't a difficulty level, so whether it belongs in
  practice mode's Easy/Normal/Impossible picker is a product decision, not wiring.
