# 0016. Human game records as training data

- **Status:** Deferred
- **Date:** 2026-09

## Context

Persisted `GameRecord`s from live tables replay through the pure engine to the full `GameState`,
so every hidden hand is recoverable. Each human game is exactly labelled data for the RL policy's
auxiliary heads ([ml.md §8](../ml.md)) and a held-out evaluation slice from the real target
distribution, which self-play only approximates.

## Why deferred

- No live human traffic yet — the corpus would be too small to matter.
- Only records matching the current `ENGINE_VERSION` replay ([ml.md §2](../ml.md)); a corpus
  spanning engine bumps is mostly unusable unless replay is pinned to old engine builds.
- Training on players' games needs a disclosure/consent line in the product first.
