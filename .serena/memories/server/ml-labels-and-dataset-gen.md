# ML Stage A/B: ground-truth labels + dataset generation (built 2026-09-28)

Continuation of `mem:server/ml-feature-encoder`. Phase 1 (docs/06-ml.md §6.2) checklist status:
encoder built, labels built, dataset generation built (boilerplate), model/training/tile_risk
integration still not started.

**Stage A — `server/bots/labels.py`:** pure `GameState`-based ground truth: `is_tenpai`,
`winning_tile_types`, `expected_faan_if_won`, `danger_labels_for_opponents`. Key constraint
discovered and respected: `tests/test_oracle_containment.py` AST-sweeps `app/`, `bots/`,
`mahjong_core/`, `ml/`, `alembic/`, `tools/` and hard-fails if `_omniscient_seat_view` is called
anywhere but `Table._submit_bot_job`. Label generation must read `GameState`/`SeatState`
directly instead — self-play/arena code already holds it, no omniscient `SeatView` needed.
`bots/arena.py` was refactored to import these from `bots/labels.py` instead of duplicating them
(`_seat_hand34`→`seat_hand34`, `_winning_tile_types`→`winning_tile_types`,
`_unused_tile_id_for_type`→`unused_tile_id_for_type`); this also closed a real, previously-flagged
gap (docs/04-bots.md §9's housekeeping note): arena's own `shanten()` calls weren't `hand_sets`-
aware, now they are via the shared `is_tenpai`. `tests/test_valuation_selfplay.py` had a third
independent duplicate of the same `seat_hand34` logic; also switched to import from `bots.labels`.

**Every faan value in `tests/test_labels.py` was computed once via the real scorer, not hand-
derived** — `平糊`/`無花`/`門前清` stack on nearly any closed hand, so a "boring" all-sequences
tenpai hand scores 3 faan (clears default `min_faan=3`), not 1, once those stack. Don't assume a
hand-authored test hand's faan without running `score_winning_hand` on it first.

**Stage B — `server/ml/generate_dataset.py`:** self-play data generation,
`python -m ml.generate_dataset --out data/danger_model --bots FaanBot,FaanBot,FaanBot,FaanBot`.
Mirrors `bots/selfplay.py`'s `play_game` stepping logic exactly but emits one row per real turn
decision (not claim-window responses -- different decision type, out of scope) via
`encode_seat_view` + `danger_labels_for_opponents`. Writes parquet shards (`--shard-games`,
default 20 games/shard). Runs forever by default (`--games 0`) until SIGINT/SIGTERM, which
flushes the in-progress shard before exiting cleanly.

**Environment gotcha:** repo-root `data/` is gitignored (and `*.parquet` too — parquet was
already the anticipated format before this work) but is **root-owned on this machine**, not
writable as the `michaels` user (likely leftover from a prior `docker compose` run creating the
bind-mount dir as root). Real dataset output for local runs goes to `server/data/danger_model`
instead (still matches the repo-wide `data/` gitignore pattern). Didn't `chown`/`pkexec` the
root-owned one — out of scope, low value, mildly invasive host change for a build artifact
directory that docker will recreate correctly anyway when actually deployed via compose.

Both `tests/test_generate_dataset.py` and `tests/test_ml_encode.py` guard on
`pytest.importorskip` for numpy/pyarrow — verified the full fast suite's pass/skip/deselect counts
reconcile exactly with and without those packages installed (13 real tests ↔ 2 skip placeholders,
one per gated file) before trusting this as safe under `make test-server`.

Not built yet: the actual model architecture/training loop (`ml/train.py` is still the
`NotImplementedError` stub), offline eval, `tile_risk` integration, arena validation gate.
