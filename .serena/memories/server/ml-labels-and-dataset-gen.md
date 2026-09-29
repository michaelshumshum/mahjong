# ML labels + dataset gen + training pipeline (updated 2026-09-29)

Phase 1 (docs/06-ml.md §6.2) status: encoder, labels, dataset gen (schema v3), packing, model,
training loop, eval, both baselines and numpy export are BUILT and committed. NOT done: the real
training run, running the baselines/eval on real data, recording results (docs stage 11),
`tile_risk` integration + arena gate.

**Labels — `bots/labels.py`:** pure `GameState`-based ground truth (`is_tenpai`, `winning_tile_types`,
`expected_faan_if_won`, `danger_labels_for_opponents`). `tests/test_oracle_containment.py` forbids
`_omniscient_seat_view` outside `Table._submit_bot_job`, so labels read `GameState` directly.
Faan values in `tests/test_labels.py` come from the real scorer, never hand-derived (平糊/無花/門前清
stack, so a plain closed tenpai hand scores 3).

**Dataset gen — `ml/generate_dataset.py`:** schema v3 rows via `ml/raw.py::raw_row` (per-tile counts,
`discard_seq`, `concealed_kongs`, `flowers`, relative-seat order). Other seats' concealed-kong tile
types are hidden (`visible_meld_counts34`); v2 data leaked them and must not be trained on.
`play_and_label(..., row_hook)` gives baselines the live GameState. Seat<->personality shuffled per
game from the game seed. Real run: `data/danger_v3` (`--games 21800 --parallel 10`, ~1.2 games/s,
~5 h; started 2026-09-29 ~12:45 under `setsid nohup`, log `server/data/danger_v3_gen.log`). Held-out
EfficiencyBot set still to generate (`data/danger_v3_heldout_eff`, seed-start 10000000).
Repo-root `data/` is root-owned; local data lives under `server/data/`.

**Pipeline commands (cwd server/):**
- `uv run python -m ml.pack --src data/danger_v3 --out data/danger_v3_packed`
- `uv run python -m ml.train --config ml/configs/danger.yaml [--resume]` -> `runs/danger/`
- `uv run python -m ml.evaluate --ckpt runs/danger/ckpt_best.pt --data data/danger_v3_packed --split test`
  (`--split all` on the held-out pack)
- `python -m ml.heuristic_baseline --data ... --ckpt ...` (replays games; slow), `python -m
  ml.gbdt_baseline ...`, `python -m ml.export --ckpt ... --out danger.npz`

**Gotchas:**
- Splits are game-level (`ml/splits.py`, TRAIN/VAL/TEST = 0/1/2; seed 2 is val, 6 is test).
- `ml/heuristic_baseline.py` tests are slow-marked (~100 s under load); latency test in
  `test_ml_export.py` is slow-marked and noisy under CPU load (~5 ms for 3 opponents, 96x6).
- `tests/ml_synthetic.py` builds a synthetic packed dataset for ml tests.
- Known heuristic bug logged in docs/99-deferred.md: `no_chance` counts the observer's own copy
  (3.4% of candidate discards scored exactly 0). FaanBot intentionally untouched.
- lefthook comment-length hook: max 2 consecutive comment lines.
- numpy is not a base dependency; serving the model in the api image needs numpy added.
